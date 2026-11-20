import json

import requests

from .common import env, log, need_env


class Telegram:
    def __init__(self):
        self.token, self.chat_id = need_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        self.base = f"https://api.telegram.org/bot{self.token}"

    def call(self, method, files=None, timeout=60, **params):
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v is not None}
        r = requests.post(f"{self.base}/{method}", data=data, files=files, timeout=timeout)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description')}")
        return body["result"]

    def send_message(self, text, reply_to=None):
        try:
            return self.call("sendMessage", chat_id=self.chat_id, text=text[:4000],
                             reply_to_message_id=reply_to, disable_web_page_preview=True)
        except Exception as e:  # notifications must never crash the bot
            log("Falha a enviar mensagem Telegram:", e)

    def send_video(self, path, caption, buttons=None):
        markup = {"inline_keyboard": [buttons]} if buttons else None
        with open(path, "rb") as f:
            res = self.call("sendVideo", files={"video": f}, timeout=300, chat_id=self.chat_id,
                            caption=caption[:1024], supports_streaming=True, reply_markup=markup)
        return res["message_id"], res["video"]["file_id"]

    def updates(self, offset):
        return self.call("getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query"])

    def answer(self, callback_id, text):
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except Exception:
            pass  # old button presses can no longer be answered; that's fine

    def mark_message(self, message_id, label):
        try:
            self.call("editMessageReplyMarkup", chat_id=self.chat_id, message_id=message_id,
                      reply_markup={"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]})
        except Exception as e:
            log("Falha a editar mensagem:", e)

    def download(self, file_id, dest):
        info = self.call("getFile", file_id=file_id)
        url = f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}"
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        return dest


def owner_chat_ok(update, chat_id):
    msg = update.get("callback_query", {}).get("message", {})
    return str(msg.get("chat", {}).get("id")) == str(chat_id)
