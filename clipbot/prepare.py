"""Find new clips, render them and send them to Telegram (for approval or straight to the queue)."""
import re
import shutil
from pathlib import Path

from .common import ROOT, clip_key, log, now_iso, save_state


def make_hook(title, cfg):
    t = re.sub(r"https?://\S+", "", title or "")
    t = " ".join(t.split())
    if len(re.sub(r"[^A-Za-z0-9]", "", t)) < 4:
        return cfg["text"]["hook_fallback"]
    limit = cfg["text"]["hook_max_chars"]
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def make_texts(clip, cfg):
    hook = make_hook(clip["title"], cfg)
    v = {"hook": hook, "streamer": clip["streamer"], "url": clip["url"], "channel_url": clip["channel_url"]}
    title = cfg["text"]["youtube_title"].format(**v)
    if len(title) > 100:  # shorten the hook, keep the credit and hashtags
        extra = len(title) - 100
        v["hook"] = hook[: max(10, len(hook) - extra - 1)] + "…"
        title = cfg["text"]["youtube_title"].format(**v)[:100]
    return {
        "hook": hook,
        "title": title,
        "description": cfg["text"]["description"].format(**v),
        "caption": cfg["text"]["tiktok_caption"].format(**v),
    }


def run(cfg, st, dry_run=False):
    from .render import render_clip
    from .sources import find_candidates

    waiting = sum(1 for c in st["clips"].values() if c["status"] in ("pending", "approved"))
    need = cfg["search"]["max_waiting"] - waiting
    if need <= 0 and not dry_run:
        log(f"Já há {waiting} vídeos à espera; nada a fazer.")
        return
    need = max(need, 1)

    tg = None if dry_run else __import__("clipbot.telegram", fromlist=["Telegram"]).Telegram()
    workdir = ROOT / "work"
    outdir = ROOT / "output"

    for clip in find_candidates(cfg, st):
        if need <= 0:
            break
        key = clip_key(clip["id"])
        texts = make_texts(clip, cfg)
        clip["_hook"] = texts["hook"]
        entry = {
            "clip_id": clip["id"], "platform": clip["platform"], "url": clip["url"],
            "streamer": clip["streamer"], "channel_url": clip["channel_url"], "views": clip["views"],
            "moment_group": clip.get("moment_group"), "moment_t": clip.get("moment_t"),
            "created": now_iso(), **texts,
        }
        try:
            video = render_clip(clip, cfg, workdir)
        except Exception as e:
            log(f"Falhou a renderizar {clip['url']}: {e}")
            if not dry_run:
                st["clips"][key] = {**entry, "status": "failed", "error": str(e)[:300]}
                save_state(st)
            continue

        if dry_run:
            outdir.mkdir(exist_ok=True)
            dest = outdir / f"{key}.mp4"
            shutil.copy(video, dest)
            log(f"[teste] vídeo pronto: {dest.name} | título: {texts['title']}")
            need -= 1
            continue

        approval = cfg.get("approval", True)
        caption = (
            f"{'🆕 Novo clip para aprovar' if approval else '📥 Adicionado à fila'}\n"
            f"👤 {entry['streamer']} ({entry['platform']}) · 👁 {entry['views']} views\n"
            f"🔗 {entry['url']}\n\n"
            f"YouTube: {texts['title']}\n\nTikTok: {texts['caption']}"
        )
        buttons = [
            {"text": "✅ Publicar", "callback_data": f"ok|{key}"},
            {"text": "❌ Rejeitar", "callback_data": f"no|{key}"},
        ] if approval else None
        msg_id, file_id = tg.send_video(video, caption, buttons)
        st["clips"][key] = {
            **entry, "status": "pending" if approval else "approved",
            "approved_at": None if approval else now_iso(),
            "tg_message_id": msg_id, "tg_file_id": file_id,
        }
        save_state(st)
        log(f"Enviado para o Telegram: {texts['title']}")
        need -= 1
