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


def make_texts(clip, cfg, hook=None):
    hook = hook or make_hook(clip["title"], cfg)
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


MAX_CUSTOM_HOOK = 80


def _send(tg, cfg, st, key, entry, video):
    approval = cfg.get("approval", True)
    caption = (
        f"{'🆕 Novo clip para aprovar' if approval else '📥 Adicionado à fila'}\n"
        f"👤 {entry['streamer']} ({entry['platform']}) · 👁 {entry['views']} views\n"
        f"🔗 {entry['url']}\n\n"
        f"YouTube: {entry['title']}\n\nTikTok: {entry['caption']}\n\n"
        f"✏️ Título fraco? Responde a esta mensagem com o título novo."
    )
    buttons = [
        {"text": "✅ Publicar", "callback_data": f"ok|{key}"},
        {"text": "❌ Rejeitar", "callback_data": f"no|{key}"},
    ] if approval else None
    from . import storage

    hq_asset = storage.save(video, key)
    msg_id, file_id = tg.send_video(video, caption, buttons)
    st["clips"][key] = {
        **entry, "status": "pending" if approval else "approved",
        "approved_at": None if approval else now_iso(),
        "tg_message_id": msg_id, "tg_file_id": file_id, "hq_asset": hq_asset,
    }
    save_state(st)
    log(f"Enviado para o Telegram: {entry['title']}")


def expire_old(cfg, st, tg):
    """Clips nobody approved within N hours make room for fresh ones."""
    from datetime import datetime, timedelta, timezone

    from . import storage

    hours = cfg["search"].get("expire_hours", 48)
    limit = datetime.now(timezone.utc) - timedelta(hours=hours)
    for e in st["clips"].values():
        if e["status"] != "pending":
            continue
        try:
            created = datetime.fromisoformat(e["created"])
        except (KeyError, ValueError):
            continue
        if created < limit:
            e["status"] = "expired"
            e["expired_count"] = e.get("expired_count", 0) + 1
            if e.get("hq_asset"):
                storage.delete(e["hq_asset"])
            if e.get("tg_message_id"):
                tg.mark_message(e["tg_message_id"], f"⌛ Expirou ({hours}h sem aprovação)")
            log(f"Expirado: {e['hook'][:50]}")
    save_state(st)


def redo_with_new_titles(cfg, st, tg, workdir):
    """Re-render clips whose title the owner changed by replying in Telegram."""
    from .render import render_clip

    for key, e in list(st["clips"].items()):
        if e["status"] != "rerender":
            continue
        hook = e["new_hook"][:MAX_CUSTOM_HOOK]
        clip = {"title": hook, "streamer": e["streamer"], "url": e["url"],
                "channel_url": e["channel_url"], "download_url": e.get("download_url") or e["url"]}
        texts = make_texts(clip, cfg, hook=hook)
        clip["_hook"] = hook
        try:
            video = render_clip(clip, cfg, workdir)
        except Exception as ex:
            log(f"Falhou a refazer {e['url']}: {ex}")
            e["redo_attempts"] = e.get("redo_attempts", 0) + 1
            if e["redo_attempts"] >= 3:
                e["status"] = "failed"
                tg.send_message(f"⚠️ Não consegui refazer o vídeo com o título novo: {ex}"[:500],
                                reply_to=e.get("tg_message_id"))
            save_state(st)
            continue
        entry = {k: v for k, v in e.items() if k not in ("new_hook", "redo_attempts", "tg_message_id",
                                                         "tg_file_id", "status", "approved_at", "hq_asset")}
        entry.update(texts)
        entry["created"] = now_iso()  # fresh clock for the 48h expiry
        try:
            _send(tg, cfg, st, key, entry, video)
        except Exception as ex:
            log(f"Falhou a enviar o vídeo refeito ({ex}); tenta de novo na próxima procura")


def run(cfg, st, dry_run=False):
    from .render import render_clip
    from .sources import find_candidates

    workdir = ROOT / "work"
    outdir = ROOT / "output"
    tg = None if dry_run else __import__("clipbot.telegram", fromlist=["Telegram"]).Telegram()

    if not dry_run:
        expire_old(cfg, st, tg)
        redo_with_new_titles(cfg, st, tg, workdir)

    waiting = sum(1 for c in st["clips"].values() if c["status"] in ("pending", "approved", "rerender"))
    need = min(cfg["search"]["max_waiting"] - waiting, cfg["search"].get("per_run", 10))
    if need <= 0 and not dry_run:
        log(f"Já há {waiting} vídeos à espera; nada a fazer.")
        return
    need = max(need, 1)

    import time
    started = time.monotonic()
    budget = cfg["search"].get("time_budget_min", 60) * 60
    for clip in find_candidates(cfg, st):
        if need <= 0:
            break
        if time.monotonic() - started > budget:
            log("Tempo da procura esgotado; o resto fica para a próxima")
            break
        key = clip_key(clip["id"])
        texts = make_texts(clip, cfg)
        clip["_hook"] = texts["hook"]
        clip["_ai_title"] = True  # Gemini may rewrite the hook once the transcript exists
        entry = {
            "clip_id": clip["id"], "platform": clip["platform"], "url": clip["url"],
            "download_url": clip["download_url"],
            "streamer": clip["streamer"], "channel_url": clip["channel_url"], "views": clip["views"],
            "moment_group": clip.get("moment_group"), "moment_t": clip.get("moment_t"),
            "created": now_iso(), **texts,
        }
        previous = st["clips"].get(key) or {}
        if previous.get("expired_count"):
            entry["expired_count"] = previous["expired_count"]
        try:
            video = render_clip(clip, cfg, workdir)
        except Exception as e:
            log(f"Falhou a renderizar {clip['url']}: {e}")
            if not dry_run:
                attempts = (st["clips"].get(key) or {}).get("attempts", 0) + 1
                st["clips"][key] = {**entry, "status": "failed", "attempts": attempts, "error": str(e)[:300]}
                save_state(st)
            continue

        if clip["_hook"] != texts["hook"]:
            texts = make_texts(clip, cfg, hook=clip["_hook"])
            entry.update(texts)
            entry["original_title"] = clip["title"]

        if dry_run:
            outdir.mkdir(exist_ok=True)
            dest = outdir / f"{key}.mp4"
            shutil.copy(video, dest)
            log(f"[teste] vídeo pronto: {dest.name} | título: {texts['title']}")
            need -= 1
            continue

        try:
            _send(tg, cfg, st, key, entry, video)
        except Exception as e:
            log(f"Falhou a enviar para o Telegram ({e}); fica para a próxima procura")
            continue
        need -= 1
