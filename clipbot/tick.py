"""Runs every ~20 min: read Telegram button presses, publish at the scheduled times."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import tiktok, youtube
from .common import ROOT, log, now_iso, save_state
from .telegram import Telegram, owner_chat_ok

GRACE = timedelta(minutes=90)  # GitHub's scheduler can be late; still publish within this window
MAX_ATTEMPTS = 3


def process_buttons(tg, st):
    updates = tg.updates(st["tg_offset"])
    for u in updates:
        st["tg_offset"] = u["update_id"] + 1
        cq = u.get("callback_query")
        if not cq or not owner_chat_ok(u, tg.chat_id):
            continue
        action, _, key = (cq.get("data") or "").partition("|")
        clip = st["clips"].get(key)
        if action not in ("ok", "no") or not clip or clip["status"] != "pending":
            tg.answer(cq["id"], "Já tratado")
            continue
        if action == "ok":
            clip["status"], clip["approved_at"] = "approved", now_iso()
            tg.answer(cq["id"], "Aprovado ✅")
            tg.mark_message(clip["tg_message_id"], "✅ Aprovado — na fila")
        else:
            clip["status"] = "rejected"
            tg.answer(cq["id"], "Rejeitado ❌")
            tg.mark_message(clip["tg_message_id"], "❌ Rejeitado")
        log(f"{clip['streamer']}: {clip['status']}")
    save_state(st)


def due_slot(cfg, st):
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    now = datetime.now(tz)
    for day in (now.date() - timedelta(days=1), now.date()):
        for s in cfg["schedule"]["slots"]:
            h, m = map(int, s.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if slot <= now < slot + GRACE and st["last_slot"] != slot.isoformat():
                return slot.isoformat()
    return None


def publish_next(cfg, st, tg):
    queue = sorted(
        (c for c in st["clips"].values() if c["status"] == "approved"),
        key=lambda c: c.get("approved_at") or "",
    )
    if not queue:
        log("Hora de publicar, mas a fila está vazia.")
        tg.send_message("⏰ Hora de publicar, mas não há vídeos aprovados na fila.")
        return
    clip = queue[0]

    use_yt = cfg["youtube"]["enabled"] and youtube.configured()
    use_tt = cfg["tiktok"]["enabled"] and tiktok.configured()
    if not (use_yt or use_tt):
        clip["status"] = "published"
        clip["published"] = {"manual": now_iso()}
        tg.send_message(
            "⏰ Hora de publicar este vídeo (YouTube/TikTok ainda não ligados — publica à mão):\n\n"
            f"YouTube: {clip['title']}\n\n{clip['description']}\n\nTikTok: {clip['caption']}",
            reply_to=clip["tg_message_id"],
        )
        return

    path = ROOT / "work" / "publish.mp4"
    path.parent.mkdir(exist_ok=True)
    tg.download(clip["tg_file_id"], path)

    results, errors = clip.setdefault("published", {}), []
    if use_yt and "youtube" not in results:
        try:
            results["youtube"] = youtube.upload(
                path, clip["title"], clip["description"], cfg["text"]["tags"],
                cfg["youtube"]["privacy"], cfg["youtube"]["category_id"])
        except Exception as e:
            errors.append(f"YouTube: {e}")
    if use_tt and "tiktok" not in results:
        try:
            results["tiktok"] = tiktok.upload(path, clip["caption"], cfg["tiktok"]["privacy"])
        except Exception as e:
            errors.append(f"TikTok: {e}")

    clip["attempts"] = clip.get("attempts", 0) + 1
    if not errors:
        clip["status"] = "published"
    elif clip["attempts"] >= MAX_ATTEMPTS:
        clip["status"] = "failed"

    lines = ["📤 Publicado!" if not errors else "⚠️ Publicação com problemas"]
    lines += [f"{k}: {v}" for k, v in results.items()]
    lines += errors
    for e in errors:
        log(e)
    tg.send_message("\n".join(lines), reply_to=clip["tg_message_id"])


def run(cfg, st):
    tg = Telegram()
    process_buttons(tg, st)
    slot = due_slot(cfg, st)
    if slot:
        log("Slot de publicação:", slot)
        st["last_slot"] = slot
        publish_next(cfg, st, tg)
        save_state(st)
