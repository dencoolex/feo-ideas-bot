# bot_poller.py
import os
import sys
import time
import requests
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")         # доступен в Actions автоматически
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")  # Actions подставит repo "owner/name"
LAST_UPDATE_FILE = "last_update.txt"
MAX_UPDATES = 100
DEFAULT_LABEL = "idea"

if not TELEGRAM_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
    sys.exit(1)
if not GITHUB_TOKEN:
    print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
    sys.exit(1)
if not GITHUB_REPOSITORY:
    print("ERROR: GITHUB_REPOSITORY not set", file=sys.stderr)
    sys.exit(1)


def read_last_update():
    try:
        with open(LAST_UPDATE_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None


def write_last_update(update_id):
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(update_id))


def get_updates(offset=None, limit=MAX_UPDATES, timeout=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"limit": limit}
    if offset is not None:
        params["offset"] = offset
    if timeout:
        params["timeout"] = timeout
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def create_github_issue(title: str, body: str, labels=None):
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def send_telegram_reply(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def process_updates(updates):
    if not updates:
        return None
    max_id = None
    for upd in updates:
        update_id = upd.get("update_id")
        if max_id is None or (update_id is not None and update_id > max_id):
            max_id = update_id

        message = upd.get("message") or upd.get("channel_post")
        if not message:
            continue

        from_user = message.get("from") or {}
        user_name = from_user.get("username")
        if not user_name:
            name_parts = [from_user.get("first_name") or "", from_user.get("last_name") or ""]
            user_name = " ".join([p for p in name_parts if p]).strip() or "unknown"

        chat = message.get("chat", {})
        chat_type = chat.get("type")
        chat_id = chat.get("id")

        text = message.get("text") or message.get("caption") or "<non-text message>"
        received_ts = message.get("date")
        try:
            ts = datetime.utcfromtimestamp(received_ts).isoformat() + "Z"
        except Exception:
            ts = ""

        snippet = (text.strip().split("\n", 1)[0])[:60]
        title = f"Идея от {user_name}: {snippet or '(без текста)'}"
        body = (
            f"**Отправитель:** {user_name}\n"
            f"**Чат id:** {chat_id} (type: {chat_type})\n"
            f"**Время (UTC):** {ts}\n\n"
            f"**Текст:**\n\n```\n{text}\n```\n\n---\nДобавлено автоматически из Telegram бот-предложения."
        )

        try:
            issue = create_github_issue(title, body, labels=[DEFAULT_LABEL])
            issue_number = issue.get("number")
            print(f"[ok] Created issue #{issue_number} for update {update_id}")
            try:
                reply_text = f"Спасибо! Ваша идея сохранена как issue #{issue_number}. Мы её рассмотрим."
                send_telegram_reply(chat_id, reply_text)
            except Exception as e:
                print(f"[warn] Failed to send reply to chat {chat_id}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[error] Creating issue failed for update {update_id}: {e}", file=sys.stderr)

    return max_id


def main():
    last = read_last_update()
    if last is None:
        print("[main] No last_update found, initializing state (no issues will be created for history)...")
        data = get_updates(limit=MAX_UPDATES)
        results = data.get("result", [])
        if results:
            max_id = max(u.get("update_id", 0) for u in results)
            write_last_update(max_id + 1)
            print(f"[main] Initialized last_update -> {max_id + 1}")
        else:
            write_last_update(1)
            print("[main] No updates present. Set last_update to 1")
        return

    offset = last
    print(f"[main] Fetching updates with offset={offset}")
    data = get_updates(offset=offset, limit=MAX_UPDATES)
    results = data.get("result", [])
    if not results:
        print("[main] No new updates.")
        return

    max_id = process_updates(results)
    if max_id is not None:
        next_offset = max_id + 1
        write_last_update(next_offset)
        print(f"[main] Updated last_update -> {next_offset}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {e}", file=sys.stderr)
        sys.exit(2)
