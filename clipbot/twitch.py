from datetime import datetime, timedelta, timezone

import requests

from .common import clip_key, log, need_env

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


def _same_moment(a, b):
    return (
        a.get("video_id")
        and a.get("video_id") == b.get("video_id")
        and a.get("vod_offset") is not None
        and b.get("vod_offset") is not None
        and abs(a["vod_offset"] - b["vod_offset"]) < 60
    )


def find_candidates(cfg, st):
    """Return new Twitch clips, best first, from the allowed streamers only."""
    tw = Twitch()
    s = cfg["search"]
    game_ids = tw.game_ids(cfg["games"])
    if not game_ids:
        log("AVISO: nenhum jogo encontrado com esses nomes na Twitch:", cfg["games"])
    users = tw.users(cfg["streamers"])
    found = {u["login"] for u in users}
    for name in cfg["streamers"]:
        if name.lower() not in found:
            log(f"AVISO: streamer '{name}' não encontrado na Twitch")

    since = datetime.now(timezone.utc) - timedelta(hours=s["lookback_hours"])
    used = list(st["clips"].values())
    out = []
    for u in users:
        for c in tw.clips(u["id"], since):
            if clip_key(c["id"]) in st["clips"]:
                continue
            if game_ids and c["game_id"] not in game_ids:
                continue
            if c["view_count"] < s["min_views"] or c["duration"] < s["min_duration"]:
                continue
            if any(_same_moment(c, x) for x in used):
                continue
            out.append(c)

    out.sort(key=lambda c: c["view_count"], reverse=True)
    # Several people often clip the same moment: keep only the most viewed one.
    unique = []
    for c in out:
        if not any(_same_moment(c, x) for x in unique):
            unique.append(c)
    log(f"{len(unique)} clips novos encontrados")
    return unique
