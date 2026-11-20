from datetime import datetime, timezone

import requests

from .common import log, need_env

API = "https://api.twitch.tv/helix"


class Twitch:
    def __init__(self):
        cid, secret = need_env("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET")
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"},
            timeout=30,
        )
        r.raise_for_status()
        self.headers = {"Client-Id": cid, "Authorization": f"Bearer {r.json()['access_token']}"}

    def _get(self, path, **params):
        r = requests.get(f"{API}/{path}", headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()["data"]

    def users(self, logins):
        return self._get("users", login=[l.lower() for l in logins][:100])

    def game_ids(self, names):
        return {g["id"] for g in self._get("games", name=names)}

    def clips(self, broadcaster_id, since):
        return self._get(
            "clips",
            broadcaster_id=broadcaster_id,
            started_at=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            first=50,
        )


def fetch(streamers, games, since):
    """Clips from Twitch, in the common format used by the bot."""
    if not streamers:
        return []
    tw = Twitch()
    game_ids = tw.game_ids(games)
    if not game_ids:
        log("AVISO (Twitch): nenhum jogo encontrado com estes nomes:", games)
    users = tw.users(streamers)
    found = {u["login"] for u in users}
    for name in streamers:
        if name.lower() not in found:
            log(f"AVISO (Twitch): streamer '{name}' não encontrado")

    out = []
    for u in users:
        for c in tw.clips(u["id"], since):
            if game_ids and c["game_id"] not in game_ids:
                continue
            created = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            out.append({
                "id": c["id"],  # Twitch ids are kept unprefixed (compatible with older state)
                "platform": "twitch",
                "url": c["url"],
                "download_url": c["url"],
                "title": c["title"],
                "streamer": c["broadcaster_name"],
                "channel_url": f"twitch.tv/{u['login']}",
                "views": c["view_count"],
                "duration": c["duration"],
                "created": created.astimezone(timezone.utc).isoformat(),
                # Used to detect several people clipping the same moment
                "moment_group": f"twitch:{c['video_id']}" if c.get("video_id") else None,
                "moment_t": c.get("vod_offset"),
            })
    log(f"Twitch: {len(out)} clips de GTA no período")
    return out
