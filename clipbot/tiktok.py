"""TikTok Content Posting API (Direct Post).

Unaudited TikTok apps can only post with privacy SELF_ONLY (private).
After TikTok approves the app, change tiktok.privacy in config.yaml.
"""
import os

import requests

from .common import env, log

API = "https://open.tiktokapis.com/v2"


def configured():
    return all(env(n) for n in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"))


def _access_token():
    r = requests.post(
        f"{API}/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": env("TIKTOK_CLIENT_KEY"),
            "client_secret": env("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "refresh_token": env("TIKTOK_REFRESH_TOKEN"),
        },
        timeout=30,
    )
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token: {data}")
    if data.get("refresh_token") and data["refresh_token"] != env("TIKTOK_REFRESH_TOKEN"):
        log("AVISO: o TikTok deu um refresh token novo; atualiza o secret TIKTOK_REFRESH_TOKEN.")
    return data["access_token"]


def upload(path, caption, privacy):
    size = os.path.getsize(path)
    if size > 64 * 1024 * 1024:
        raise RuntimeError("vídeo demasiado grande para envio num só bloco")
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}

    info = requests.post(f"{API}/post/publish/creator_info/query/", headers=headers, timeout=30).json()
    allowed = info.get("data", {}).get("privacy_level_options", [])
    if allowed and privacy not in allowed:
        log(f"AVISO: privacidade {privacy} não permitida ({allowed}); a usar {allowed[0]}")
        privacy = allowed[0]

    init = requests.post(
        f"{API}/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {"title": caption[:2200], "privacy_level": privacy,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                          "video_cover_timestamp_ms": 1000},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": size, "total_chunk_count": 1},
        },
        timeout=30,
    ).json()
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init: {init['error']}")
    data = init["data"]

    with open(path, "rb") as f:
        r = requests.put(
            data["upload_url"],
            headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                     "Content-Range": f"bytes 0-{size - 1}/{size}"},
            data=f, timeout=300,
        )
    r.raise_for_status()
    log("TikTok OK:", data["publish_id"], "privacidade:", privacy)
    return f"publish_id {data['publish_id']} ({privacy})"
