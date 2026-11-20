import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"


def log(*args):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}]", *args, flush=True)


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
