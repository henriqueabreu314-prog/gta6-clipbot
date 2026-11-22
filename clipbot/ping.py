"""Check that the Telegram secrets work, with clear messages for each kind of mistake."""
import requests

from .common import env


def run():
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token:
        raise SystemExit("❌ O secret TELEGRAM_BOT_TOKEN não existe ou está vazio.")
    if not chat:
        raise SystemExit("❌ O secret TELEGRAM_CHAT_ID não existe ou está vazio.")

    # Format check without revealing the token in the logs
    head, sep, tail = token.partition(":")
    if not (head.isdigit() and sep and len(tail) >= 30) or " " in token:
        raise SystemExit(
            "❌ O TELEGRAM_BOT_TOKEN não tem o formato certo (NÚMEROS:LETRAS, sem espaços). "
            f"Tem {len(token)} caracteres; um token normal tem ~46. Volta a colá-lo do BotFather."
        )

    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=30).json()
    if not r.get("ok"):
        raise SystemExit(f"❌ O Telegram recusou o token ({r.get('error_code')} {r.get('description')}). "
                         "Usa /token no BotFather para ver o token atual e atualiza o secret.")
    print(f"✅ Token OK — bot @{r['result']['username']}")

    if not chat.lstrip("-").isdigit():
        raise SystemExit("❌ O TELEGRAM_CHAT_ID tem de ser só um número (o Id que o @userinfobot te deu).")
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": "✅ O GTA 6 Clip Bot está ligado ao teu Telegram!"},
                      timeout=30).json()
    if not r.get("ok"):
        raise SystemExit(f"❌ O token funciona mas não consegui mandar-te mensagem ({r.get('description')}). "
                         "Confirma o TELEGRAM_CHAT_ID e se carregaste em Start / mandaste 'olá' ao teu bot.")
    print("✅ Mensagem de teste enviada para o Telegram")
