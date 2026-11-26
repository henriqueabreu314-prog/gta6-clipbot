"""Runs every ~20 min: read Telegram button presses, publish at the scheduled times."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import tiktok, youtube
from .common import ROOT, log, now_iso, save_state
from .telegram import Telegram, owner_chat_ok

GRACE = timedelta(minutes=150)  # GitHub's scheduler can be late; still publish within this window
MAX_ATTEMPTS = 3


APPROVE_WORDS = {"✅", "ok", "sim", "s", "yes", "y", "publicar", "publica", "aprovar", "aprovado", "aprova", "👍"}
REJECT_WORDS = {"❌", "não", "nao", "n", "no", "rejeitar", "rejeita", "rejeitado", "apagar", "👎"}


def _handle_title_reply(tg, st, msg):
    """Owner replied to a clip's message with text -> use it as the new title."""
    reply_to = (msg.get("reply_to_message") or {}).get("message_id")
    text = " ".join((msg.get("text") or "").split())
    if not reply_to or not text or text.startswith("/"):
        return
    key, clip = next(((k, c) for k, c in st["clips"].items() if c.get("tg_message_id") == reply_to), (None, None))
    if not clip:
        tg.send_message("Não encontrei esse vídeo. Responde diretamente à mensagem do vídeo.",
                        reply_to=msg["message_id"])
        return
    if clip["status"] not in ("pending", "approved"):
        tg.send_message("Esse vídeo já foi publicado ou rejeitado; não dá para mudar o título.",
                        reply_to=msg["message_id"])
        return
    word = text.lower().strip(" .!")
    if word in APPROVE_WORDS or word in REJECT_WORDS:
        approve = word in APPROVE_WORDS
        if approve and clip["status"] == "approved":
            tg.send_message("Esse vídeo já está na fila ✅", reply_to=msg["message_id"])
            return
        clip["status"] = "approved" if approve else "rejected"
        if approve:
            clip["approved_at"] = now_iso()
        elif clip.get("hq_asset"):
            from . import storage
            storage.delete(clip["hq_asset"])
        tg.mark_message(clip["tg_message_id"], "✅ Aprovado — na fila" if approve else "❌ Rejeitado")
        tg.send_message("✅ Aprovado — está na fila." if approve else "❌ Rejeitado.", reply_to=msg["message_id"])
        log(f"{clip['streamer']}: {clip['status']} (por resposta)")
        return
    clip["new_hook"], clip["status"] = text, "rerender"
    tg.mark_message(clip["tg_message_id"], "✏️ A refazer com título novo…")
    tg.send_message(f"✏️ Título novo guardado: \"{text[:80]}\"\n"
                    "Vou refazer o vídeo e mando-te a versão nova para aprovares "
                    "(na próxima procura, até 3h — ou corre já o workflow \"Preparar clips\").",
                    reply_to=msg["message_id"])
    log(f"{clip['streamer']}: título novo -> {text}")


COMMANDS = [
    ("clips", "Procurar clips novos agora"),
    ("publicar", "Publicar já o próximo vídeo aprovado"),
    ("fila", "Ver o que está à espera e na fila"),
    ("ajuda", "Ver os comandos"),
]


def _queue_summary(st):
    clips = list(st["clips"].values())
    pend = [c for c in clips if c["status"] == "pending"]
    appr = sorted((c for c in clips if c["status"] == "approved"), key=lambda c: c.get("approved_at") or "")
    redo = [c for c in clips if c["status"] == "rerender"]
    lines = [f"📋 Por aprovar: {len(pend)} · Na fila: {len(appr)} · A refazer: {len(redo)}"]
    for i, c in enumerate(appr[:5], 1):
        lines.append(f"{i}. {c['streamer']}: {c['hook'][:50]}")
    return "\n".join(lines)


def _handle_command(tg, st, msg):
    """Returns True if the owner asked to publish now."""
    cmd = (msg.get("text") or "").split()[0].lstrip("/").split("@")[0].lower()
    reply = msg["message_id"]
    if cmd == "clips":
        import subprocess
        r = subprocess.run(["gh", "workflow", "run", "prepare.yml"], capture_output=True, text=True)
        if r.returncode == 0:
            tg.send_message("🔎 A procurar clips novos… chegam em 5–10 minutos.", reply_to=reply)
        else:
            tg.send_message(f"⚠️ Não consegui iniciar a procura: {r.stderr.strip()[:300]}", reply_to=reply)
    elif cmd == "publicar":
        tg.send_message("📤 A publicar o próximo vídeo aprovado…", reply_to=reply)
        return True
    elif cmd == "fila":
        tg.send_message(_queue_summary(st), reply_to=reply)
    else:
        tg.send_message("Comandos:\n" + "\n".join(f"/{c} — {d}" for c, d in COMMANDS)
                        + "\n\n✏️ Para mudar um título, responde à mensagem do vídeo com o título novo.",
                        reply_to=reply)
    return False


def process_buttons(tg, st):
    publish_now = False
    updates = tg.updates(st["tg_offset"])
    events = st.setdefault("events", [])

    def note(text):
        events.append(f"{now_iso()} {text}")
        del events[:-40]  # keep the last 40, for diagnosis
        log(text)

    for u in updates:
        st["tg_offset"] = u["update_id"] + 1
        kind = "callback" if u.get("callback_query") else "message" if u.get("message") else ",".join(u)
        if not owner_chat_ok(u, tg.chat_id):
            note(f"ignorado ({kind}) de outro chat")
            continue
        if u.get("message"):
            m = u["message"]
            note(f"mensagem: {(m.get('text') or '')[:60]!r} resposta_a={(m.get('reply_to_message') or {}).get('message_id')}")
            if (u["message"].get("text") or "").startswith("/"):
                publish_now |= _handle_command(tg, st, u["message"])
            else:
                _handle_title_reply(tg, st, u["message"])
            continue
        cq = u.get("callback_query")
        if not cq:
            continue
        action, _, key = (cq.get("data") or "").partition("|")
        clip = st["clips"].get(key)
        msg_id = (cq.get("message") or {}).get("message_id")
        note(f"botão {cq.get('data')!r} na msg {msg_id} -> clip {'encontrado: ' + clip['status'] if clip else 'NÃO encontrado'}")
        if action not in ("ok", "no") or not clip or clip["status"] != "pending":
            tg.answer(cq["id"], "Já tratado")
            if action in ("ok", "no"):
                why = ("esse vídeo já não existe" if not clip else
                       f"esse vídeo já está {'na fila' if clip['status'] == 'approved' else clip['status']}")
                if clip and clip["status"] == "pending":
                    pass
                elif clip and clip.get("tg_message_id") != msg_id and clip["status"] == "pending":
                    why = "esta é uma versão antiga; usa a mensagem mais recente do vídeo"
                tg.send_message(f"ℹ️ Botão ignorado: {why}.", reply_to=msg_id)
            continue
        if action == "ok":
            clip["status"], clip["approved_at"] = "approved", now_iso()
            tg.answer(cq["id"], "Aprovado ✅")
            tg.mark_message(clip["tg_message_id"], "✅ Aprovado — na fila")
        else:
            clip["status"] = "rejected"
            if clip.get("hq_asset"):
                from . import storage
                storage.delete(clip["hq_asset"])
            tg.answer(cq["id"], "Rejeitado ❌")
            tg.mark_message(clip["tg_message_id"], "❌ Rejeitado")
        log(f"{clip['streamer']}: {clip['status']}")
    save_state(st)
    return publish_now


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
    from . import storage

    results, errors = clip.setdefault("published", {}), []
    got_file = False
    sources = ([("release", lambda: storage.load(clip["hq_asset"], path))] if clip.get("hq_asset") else []) + \
              [("telegram", lambda: tg.download(clip["tg_file_id"], path))]
    for name, fetch in sources:
        try:
            fetch()
            got_file = True
            break
        except Exception as e:
            errors.append(f"Ficheiro ({name}): {str(e)[:200]}")
    if not got_file:
        use_yt = use_tt = False  # nothing to upload; counted as a failed attempt below
    else:
        errors = []  # a fallback source worked
    if use_yt and "youtube" not in results:
        try:
            results["youtube"] = youtube.upload(
                path, clip["title"], clip["description"], cfg["text"]["tags"],
                cfg["youtube"]["privacy"], cfg["youtube"]["category_id"])
        except Exception as e:
            detail = getattr(e, "content", b"")
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", "replace")
            errors.append(f"YouTube: {type(e).__name__}: {e} {detail}".strip())
    if use_tt and "tiktok" not in results:
        try:
            results["tiktok"] = tiktok.upload(path, clip["caption"], cfg["tiktok"]["privacy"])
        except Exception as e:
            errors.append(f"TikTok: {e}")

    clip["attempts"] = clip.get("attempts", 0) + 1
    clip["last_errors"] = [e[:500] for e in errors] or None  # kept in state.json for diagnosis
    if not errors:
        clip["status"] = "published"
        if clip.get("hq_asset"):
            storage.delete(clip["hq_asset"])
    elif clip["attempts"] >= MAX_ATTEMPTS:
        clip["status"] = "failed"
        if clip.get("hq_asset"):
            storage.delete(clip["hq_asset"])

    lines = ["📤 Publicado!" if not errors else "⚠️ Publicação com problemas"]
    lines += [f"{k}: {v}" for k, v in results.items()]
    lines += errors
    for e in errors:
        log(e)
    tg.send_message("\n".join(lines), reply_to=clip["tg_message_id"])


def run(cfg, st, publish_now=False):
    tg = Telegram()
    if not st.get("commands_set"):
        try:
            tg.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
            st["commands_set"] = True
        except Exception as e:
            log("Falha a registar comandos no Telegram:", e)
    publish_now = process_buttons(tg, st) or publish_now
    if publish_now:
        log("Publicar já (pedido manual)")
        publish_next(cfg, st, tg)
        save_state(st)
        return
    slot = due_slot(cfg, st)
    if slot:
        log("Slot de publicação:", slot)
        st["last_slot"] = slot
        publish_next(cfg, st, tg)
        save_state(st)
