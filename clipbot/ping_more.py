"""Check the Twitch and Gemini secrets (without exposing them)."""
import sys

import requests

from .common import env


def twitch():
    cid, secret = env("TWITCH_CLIENT_ID"), env("TWITCH_CLIENT_SECRET")
    missing = [n for n, v in (("TWITCH_CLIENT_ID", cid), ("TWITCH_CLIENT_SECRET", secret)) if not v]
    if missing:
        return f"❌ Twitch: faltam os secrets {', '.join(missing)} (nome exato, em Settings → Secrets and variables → Actions → Repository secrets)"
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30,
                      params={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    if r.status_code != 200:
        return f"❌ Twitch recusou as chaves ({r.status_code}: {r.json().get('message', '')}). Confirma o Client ID e gera um Client Secret novo."
    token = r.json()["access_token"]
    g = requests.get("https://api.twitch.tv/helix/games", timeout=30, params={"name": "Grand Theft Auto VI"},
                     headers={"Client-Id": cid, "Authorization": f"Bearer {token}"}).json().get("data", [])
    return f"✅ Twitch OK — categoria GTA VI {'encontrada' if g else 'NÃO encontrada'}"


def gemini():
    key = env("GEMINI_API_KEY")
    if not key:
        return "❌ Gemini: falta o secret GEMINI_API_KEY"
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", timeout=30,
                     headers={"x-goog-api-key": key})
    if r.status_code != 200:
        msg = (r.json().get("error") or {}).get("message", "")[:200]
        return f"❌ Gemini recusou a chave ({r.status_code}: {msg})"
    flash = [m["name"] for m in r.json().get("models", []) if "flash" in m["name"]]
    return f"✅ Gemini OK — {len(flash)} modelos flash disponíveis"


def run():
    results = [twitch(), gemini()]
    print("\n".join(results))
    if any(r.startswith("❌") for r in results):
        sys.exit(1)
