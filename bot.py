import os
import sys
import time
import json
from collections import defaultdict, deque
from typing import Any, Dict, Optional, Tuple

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set", file=sys.stderr)
    sys.exit(1)
if not ADMIN_CHAT_ID:
    print("ERROR: ADMIN_CHAT_ID is not set", file=sys.stderr)
    sys.exit(1)

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

WELCOME_HTML = (
    "👋 <b>Добро пожаловать!</b>\n\n"
    "Спасибо, что написали боту идей. Отправьте свою идею в одном сообщении — "
    "<b>краткий заголовок</b> и несколько предложений. 📝\n"
    "Можно приложить фото или файл. 📸\n\n"
    "После отправки <b>админ получит уведомление</b> и ответит при необходимости. ✅"
)

LONG_POLL_TIMEOUT = 50
SLEEP_ON_ERROR = 2

RETRIES = 3
BACKOFF_BASE = 1.5

ANTI_FLOOD_ENABLED = True
FLOOD_N = 5
FLOOD_WINDOW_SEC = 60
FLOOD_COOLDOWN_SEC = 120

_user_msgs: Dict[int, deque] = defaultdict(deque)
_user_cooldown: Dict[int, float] = {}


def tg_call(method: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    url = f"{API_BASE}/{method}"
    last_exc = None
    for attempt in range(RETRIES):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if r.status_code != 200:
                try:
                    err = r.json()
                except Exception:
                    err = {"raw": r.text}
                raise RuntimeError(f"Telegram API {method} HTTP {r.status_code}: {err}")
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API {method} not ok: {data}")
            return data
        except Exception as e:
            last_exc = e
            wait = BACKOFF_BASE * (2 ** attempt)
            print(f"[tg_call] {method} attempt {attempt+1}/{RETRIES} error: {e}", file=sys.stderr)
            if attempt < RETRIES - 1:
                time.sleep(wait)
    raise last_exc  # type: ignore


def tg_get_updates(offset: Optional[int]) -> Tuple[list, Optional[int]]:
    payload = {"timeout": LONG_POLL_TIMEOUT, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    data = tg_call("getUpdates", payload, timeout=LONG_POLL_TIMEOUT + 10)
    result = data.get("result") or []
    new_offset = (result[-1]["update_id"] + 1) if result else None
    return result, new_offset


def is_private_chat(msg: Dict[str, Any]) -> bool:
    return (msg.get("chat") or {}).get("type") == "private"


def message_type(msg: Dict[str, Any]) -> str:
    for k in ("text", "photo", "document", "voice", "video", "sticker"):
        if k in msg:
            return k
    return "other"


def anti_flood_check(user_id: int) -> Tuple[bool, Optional[str]]:
    if not ANTI_FLOOD_ENABLED:
        return True, None

    now = time.time()
    cooldown_until = _user_cooldown.get(user_id)
    if cooldown_until and now < cooldown_until:
        return False, "Слишком много сообщений. Пожалуйста, попробуйте позже."

    q = _user_msgs[user_id]
    q.append(now)
    while q and now - q[0] > FLOOD_WINDOW_SEC:
        q.popleft()

    if len(q) > FLOOD_N:
        _user_cooldown[user_id] = now + FLOOD_COOLDOWN_SEC
        return False, "Слишком много сообщений за короткое время. Подождите немного и попробуйте снова."

    return True, None


def send_welcome(chat_id: int):
    tg_call(
        "sendMessage",
        {"chat_id": chat_id, "text": WELCOME_HTML, "parse_mode": "HTML", "disable_web_page_preview": True},
    )


def send_text(chat_id: int, text: str):
    tg_call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


def forward_to_admin(from_chat_id: int, message_id: int):
    tg_call("forwardMessage", {"chat_id": ADMIN_CHAT_ID, "from_chat_id": from_chat_id, "message_id": message_id})


def handle_update(update: Dict[str, Any]):
    msg = update.get("message")
    if not msg or not is_private_chat(msg):
        return

    chat_id = (msg.get("chat") or {}).get("id")
    from_user = msg.get("from") or {}
    user_id = from_user.get("id")
    username = from_user.get("username") or ""
    mid = msg.get("message_id")
    mtype = message_type(msg)

    print(f"[update] user_id={user_id} @{username} chat_id={chat_id} message_id={mid} type={mtype}")

    allowed, warn = anti_flood_check(int(user_id))
    if not allowed:
        if warn:
            try:
                send_text(int(chat_id), warn)
            except Exception as e:
                print(f"[anti_flood] warn failed: {e}", file=sys.stderr)
        return

    try:
        send_welcome(int(chat_id))
        print("[welcome] sent")
    except Exception as e:
        print(f"[welcome] error: {e}", file=sys.stderr)

    try:
        forward_to_admin(int(chat_id), int(mid))
        print("[forward] OK -> admin")
    except Exception as e:
        print(f"[forward] error: {e}", file=sys.stderr)


def main():
    print("[main] starting long polling...")
    offset = None
    while True:
        try:
            updates, new_offset = tg_get_updates(offset)
            for upd in updates:
                try:
                    handle_update(upd)
                except Exception as e:
                    print(f"[handle_update] error: {e}\nupdate={json.dumps(upd, ensure_ascii=False)}", file=sys.stderr)
            if new_offset is not None:
                offset = new_offset
        except Exception as e:
            print(f"[polling] error: {e}", file=sys.stderr)
            time.sleep(SLEEP_ON_ERROR)


if __name__ == "__main__":
    main()
