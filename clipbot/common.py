import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"


DIAG = []  # notes from this run, saved in state.json so problems can be diagnosed without the logs


def log(*args):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}]", *args, flush=True)


_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),                 # Google API keys
    re.compile(r"(?i)(key|token|secret|password)=[^&\s]+"),  # credentials in URLs
    re.compile(r"\d{8,10}:[0-9A-Za-z_\-]{30,}"),           # Telegram bot tokens
    re.compile(r"github_pat_[0-9A-Za-z_]+|gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"GOCSPX-[0-9A-Za-z_\-]+|1//0[0-9A-Za-z_\-]{20,}|ya29\.[0-9A-Za-z_\-\.]+"),
]


def redact(text):
    text = str(text)
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[escondido]", text)
    for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TWITCH_CLIENT_SECRET", "YT_CLIENT_SECRET",
                 "YT_REFRESH_TOKEN", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value and len(value) > 6:
            text = text.replace(value, "[escondido]")
    return text


def diag(*args):
    text = redact(" ".join(str(a) for a in args))
    log(text)
    text = text[:300]
    if text not in DIAG:  # the same problem once is enough
        DIAG.append(text)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
    else:
        st = {}
    st.setdefault("clips", {})
    st.setdefault("tg_offset", 0)
    st.setdefault("last_slot", None)
    return st


def save_state(st):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)
    tmp.replace(STATE_PATH)


def clip_key(twitch_id):
    """Short key (fits Telegram's 64-byte callback_data)."""
    return hashlib.sha1(twitch_id.encode()).hexdigest()[:12]


def env(name):
    v = os.environ.get(name, "").strip()
    return v or None


def need_env(*names):
    missing = [n for n in names if not env(n)]
    if missing:
        raise SystemExit(f"Faltam secrets no GitHub: {', '.join(missing)} (ver README)")
    return [env(n) for n in names]
