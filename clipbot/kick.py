"""Kick clips.

Kick's official API (api.kick.com/public/v1) has no endpoint to list clips,
so this uses the same public endpoint the kick.com website uses:
    https://kick.com/api/v2/channels/<slug>/clips?sort=view&time=week
kick.com is behind Cloudflare, which often blocks scripts. To get through,
we use curl_cffi, which makes the request look like a normal Chrome browser.
"""
import time
from datetime import datetime, timezone

from .common import log

BASE = "https://kick.com/api/v2"


def _session():
    try:
        from curl_cffi import requests as cr

        s = cr.Session(impersonate="chrome")
    except ImportError:
        import requests

        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
        )
    s.headers["Accept"] = "application/json"
    return s


def _time_window(hours):
    if hours <= 24:
        return "day"
    if hours <= 24 * 7:
        return "week"
    return "month"


def _parse_dt(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get_clips(sess, slug, window):
    for attempt in range(3):
        r = sess.get(f"{BASE}/channels/{slug}/clips", params={"sort": "view", "time": window}, timeout=30)
        if r.status_code == 200:
            return r.json().get("clips", [])
        if r.status_code == 404:
            log(f"AVISO (Kick): canal '{slug}' não encontrado")
            return []
        log(f"Kick respondeu {r.status_code} para '{slug}' (tentativa {attempt + 1}/3)")
        time.sleep(3 * (attempt + 1))
    log(f"AVISO (Kick): não foi possível ler os clips de '{slug}' (bloqueio da Cloudflare?)")
    return []


def _matches_game(clip, games):
    cat = clip.get("category") or {}
    names = {str(cat.get("name", "")).lower(), str(cat.get("slug", "")).lower().replace("-", " ")}
    wanted = {g.lower() for g in games}
    return bool(names & wanted)


def fetch(streamers, games, since):
    """Clips from Kick, in the common format used by the bot."""
    if not streamers:
        return []
    sess = _session()
    hours = (datetime.now(timezone.utc) - since).total_seconds() / 3600
    window = _time_window(hours)
    out = []
    for slug in streamers:
        slug = slug.lower().strip()
        for c in _get_clips(sess, slug, window):
            created = _parse_dt(c.get("created_at"))
            if created and created < since:
                continue
            if games and not _matches_game(c, games):
                continue
            src = c.get("video_url") or c.get("clip_url")
            if not src:
                continue
            ch = c.get("channel") or {}
            ch_slug = ch.get("slug") or slug
            out.append({
                "id": f"kick:{c['id']}",
                "platform": "kick",
                "url": f"https://kick.com/{ch_slug}/clips/{c['id']}",
                "download_url": src,
                "title": c.get("title") or "",
                "streamer": ch.get("username") or ch_slug,
                "channel_url": f"kick.com/{ch_slug}",
                "views": int(c.get("views") or c.get("view_count") or 0),
                "duration": float(c.get("duration") or 0),
                "created": (created or datetime.now(timezone.utc)).isoformat(),
                "moment_group": f"kick:{c['livestream_id']}" if c.get("livestream_id") else None,
                "moment_t": created.timestamp() if created else None,
            })
        time.sleep(1)  # be gentle with kick.com
    log(f"Kick: {len(out)} clips de GTA no período")
    return out
