"""Catchy titles written by Google Gemini (free tier), from the clip's transcript.

Needs the secret GEMINI_API_KEY. Without it (or if Gemini fails) the bot keeps
the original clip title, so this can never block a video.
"""
import json
import re

import requests

from .common import env, log

API = "https://generativelanguage.googleapis.com/v1beta"
_model_cache = {}

PROMPT = """You write the on-screen hook for a viral YouTube Short / TikTok: a GTA 6 clip from a famous live streamer.
The hook is the ONLY thing viewers read in the first second, so it must make them stop scrolling.

Streamer: {streamer}
Original clip title (written by a random viewer, usually weak): {title}
What is said in the clip (auto transcript, may contain errors):
\"\"\"{transcript}\"\"\"

Styles that work on the biggest clip channels (adapt, don't copy):
- Tension/payoff: "{streamer} thought he escaped… then THIS happened"
- Superlative: "The CRAZIEST police chase in GTA 6 history"
- Reaction: "{streamer} can't believe what GTA 6 just did"
- Fail: "{streamer}'s plan goes HORRIBLY wrong in GTA 6"
- Curiosity gap: "Nobody expected this in Vice City"
- POV / relatable: "POV: you finally get a 5 star wanted level"
- Direct quote when the transcript has a funny line: '"I'm never doing that again" - {streamer}'

Rules:
- English, max {max_chars} characters, Title Case or 1-2 CAPS words for emphasis
- be specific to THIS clip (use details from the transcript: cops, car, Lucia, heist, money, death, a quote...)
- never invent events that the transcript or original title don't support; if unsure, use curiosity instead of facts
- the streamer's name helps search: use it in most options
- at most one emoji, at the end (💀 😭 😂 🤯 🔥 😳); no hashtags, no quotation marks around the whole title

Write 5 different options in different styles, then pick the one most likely to get clicks.
Return JSON: {{"options": ["...", "...", "...", "...", "..."], "best": "<the chosen option, copied exactly>"}}"""


def configured():
    return bool(env("GEMINI_API_KEY"))


def _pick_model(preferred):
    if preferred in _model_cache:
        return _model_cache[preferred]
    key = env("GEMINI_API_KEY")
    r = requests.get(f"{API}/models", params={"key": key, "pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    if preferred in names:
        choice = preferred
    else:  # model renamed/retired: use the newest "flash" model available
        flash = sorted((n for n in names if "flash" in n and "preview" not in n and "exp" not in n), reverse=True)
        choice = (flash or names)[0]
        log(f"Gemini: modelo '{preferred}' indisponível, a usar '{choice}'")
    _model_cache[preferred] = choice
    return choice


def _clean(text, max_chars):
    text = re.sub(r"#\w+", "", text).strip().strip('"').strip("'")
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return text


def make_hook(clip, words, cfg):
    """Return an AI-written hook, or None to keep the original title."""
    if not configured():
        return None
    tcfg = cfg.get("titles") or {}
    if tcfg.get("enabled", True) is False:
        return None
    max_chars = cfg["text"]["hook_max_chars"]
    transcript = " ".join(w[2] for w in words)[:3000] or "(no speech detected)"
    prompt = PROMPT.format(streamer=clip.get("streamer", ""), title=clip.get("title", ""),
                           transcript=transcript, max_chars=max_chars)
    try:
        model = _pick_model(tcfg.get("model", "gemini-2.5-flash"))
        r = requests.post(
            f"{API}/models/{model}:generateContent",
            params={"key": env("GEMINI_API_KEY")},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}},
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        best = data.get("best") or data.get("title") or (data.get("options") or [""])[0]
        title = _clean(best, max_chars)
        if len(title) < 8:
            return None
        log(f"Título IA: {title}")
        return title
    except Exception as e:
        log(f"Gemini falhou ({str(e)[:200]}); a usar o título original")
        return None
