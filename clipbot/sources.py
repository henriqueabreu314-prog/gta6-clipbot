"""Collect clips from every platform, filter and rank them."""
from datetime import datetime, timedelta, timezone

from . import kick, twitch
from .common import clip_key, log


def streamers_by_platform(cfg):
    s = cfg.get("streamers") or {}
    if isinstance(s, list):  # old format: a plain list means Twitch
        return {"twitch": s, "kick": []}
    return {"twitch": s.get("twitch") or [], "kick": s.get("kick") or []}


def _same_moment(a, b):
    return (
        a.get("moment_group")
        and a.get("moment_group") == b.get("moment_group")
        and a.get("moment_t") is not None
        and b.get("moment_t") is not None
        and abs(a["moment_t"] - b["moment_t"]) < 60
    )


def find_candidates(cfg, st):
    s = cfg["search"]
    since = datetime.now(timezone.utc) - timedelta(hours=s["lookback_hours"])
    names = streamers_by_platform(cfg)

    clips = []
    for platform, mod in (("twitch", twitch), ("kick", kick)):
        try:
            clips += mod.fetch(names[platform], cfg["games"], since)
        except SystemExit as e:  # missing secrets for one platform shouldn't stop the other
            log(f"{platform}: {e}")
        except Exception as e:
            log(f"Erro ao procurar clips na {platform}: {e}")

    used = list(st["clips"].values())
    fresh = [
        c for c in clips
        if clip_key(c["id"]) not in st["clips"]
        and c["views"] >= s["min_views"]
        and c["duration"] >= s["min_duration"]
        and not any(_same_moment(c, x) for x in used)
    ]
    fresh.sort(key=lambda c: c["views"], reverse=True)

    # Several people often clip the same moment: keep only the most viewed one.
    unique = []
    for c in fresh:
        if not any(_same_moment(c, x) for x in unique):
            unique.append(c)
    log(f"{len(unique)} clips novos para usar")
    return unique
