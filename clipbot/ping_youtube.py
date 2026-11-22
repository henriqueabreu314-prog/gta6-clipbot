"""Check that the YouTube secrets work (without uploading anything)."""
import requests

from .common import env


def run():
    names = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    missing = [n for n in names if not env(n)]
    if missing:
        raise SystemExit(f"❌ Faltam os secrets: {', '.join(missing)}")

    cid, secret, refresh = (env(n) for n in names)
    if not cid.endswith(".apps.googleusercontent.com"):
        raise SystemExit("❌ O YT_CLIENT_ID devia acabar em .apps.googleusercontent.com")
    if not refresh.startswith("1//"):
        raise SystemExit("❌ O YT_REFRESH_TOKEN devia começar por 1//")

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": secret,
        "refresh_token": refresh, "grant_type": "refresh_token",
    }, timeout=30).json()
    if "access_token" not in r:
        err = r.get("error")
        hint = {
            "invalid_client": "Client ID ou Client secret errados (confirma que usaste o secret NOVO).",
            "invalid_grant": "Refresh token inválido ou revogado. Tira um novo no OAuth Playground.",
            "unauthorized_client": "O refresh token foi gerado com outro Client ID/secret.",
        }.get(err, "")
        raise SystemExit(f"❌ A Google recusou as chaves ({err}: {r.get('error_description')}). {hint}")

    info = requests.get("https://oauth2.googleapis.com/tokeninfo",
                        params={"access_token": r["access_token"]}, timeout=30).json()
    scopes = info.get("scope", "")
    if "youtube.upload" not in scopes and "auth/youtube" not in scopes:
        raise SystemExit(f"❌ O token não tem permissão de upload (scopes: {scopes}). "
                         "No Playground usa o scope https://www.googleapis.com/auth/youtube.upload")
    print("✅ Chaves do YouTube OK — permissão de upload confirmada")
