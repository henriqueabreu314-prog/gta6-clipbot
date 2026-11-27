"""Catchy titles written by Google Gemini (free tier), from the clip's transcript.

Needs the secret GEMINI_API_KEY. Without it (or if Gemini fails) the bot keeps
the original clip title, so this can never block a video.
"""
import json
import re

import requests

from .common import diag, env, log

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


def _headers():
    # The key goes in a header, never in the URL (URLs end up in error messages)
    return {"x-goog-api-key": env("GEMINI_API_KEY") or ""}


def configured():
    return bool(env("GEMINI_API_KEY"))


_bad_models = set()


def _candidates(preferred):
    """Preferred model first, then other text models from the account's list, newest first."""
    r = requests.get(f"{API}/models", headers=_headers(), params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]

    def score(n):  # prefer stable flash models, newest version first
        nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", n)[:1]] or [0]
        return ("flash" in n, "latest" in n, not any(t in n for t in ("preview", "exp", "lite", "image", "tts")), nums[0])

    others = sorted((n for n in names if n != preferred), key=score, reverse=True)
    return [m for m in [preferred] + others if m not in _bad_models]


def _clean(text, max_chars):
    text = re.sub(r"#\w+", "", text).strip().strip('"').strip("'")
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return text


def make_hook(clip, words, cfg):
    """Return an AI-written hook, or None to keep the original title."""
    if not configured():
        diag("Gemini: secret GEMINI_API_KEY não está definido")
        return None
    tcfg = cfg.get("titles") or {}
    if tcfg.get("enabled", True) is False:
        return None
    max_chars = cfg["text"]["hook_max_chars"]
    transcript = " ".join(w[2] for w in words)[:3000] or "(no speech detected)"
    prompt = PROMPT.format(streamer=clip.get("streamer", ""), title=clip.get("title", ""),
                           transcript=transcript, max_chars=max_chars)
    try:
        cands = _model_cache.get("cands") or _candidates(tcfg.get("model", "gemini-flash-latest"))
        _model_cache["cands"] = cands
        last_error = None
        for model in cands[:4]:
            r = requests.post(
                f"{API}/models/{model}:generateContent",
                headers=_headers(),
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}},
                timeout=60,
            )
            if r.status_code in (400, 403, 404):  # model not available for this account: try the next one
                last_error = f"{model}: {r.status_code} {r.text[:150]}"
                _bad_models.add(model)
                continue
            r.raise_for_status()
            if model != cands[0]:
                diag(f"Gemini: a usar o modelo {model}")
                _model_cache["cands"] = [model] + [c for c in cands if c != model]
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
            best = data.get("best") or data.get("title") or (data.get("options") or [""])[0]
            title = _clean(best, max_chars)
            if len(title) < 8:
                return None
            log(f"Título IA: {title}")
            return title
        raise RuntimeError(f"nenhum modelo Gemini disponível ({last_error})")
    except Exception as e:
        detail = ""
        resp = getattr(e, "response", None)
        if resp is not None:
            detail = (resp.text or "")[:300]
        diag(f"Gemini falhou ({str(e)[:200]} {detail}); a usar o título original")
        return None
