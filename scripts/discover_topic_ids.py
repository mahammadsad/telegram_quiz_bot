"""Admin-only Telegram forum thread-ID discovery via /topicid <key>."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.subjects import get_subject  # noqa: E402


def main() -> None:
    token = _required("TELEGRAM_BOT_TOKEN")
    expected_chat = int(_required("TELEGRAM_CHAT_ID"))
    configured_admins = _admin_ids(os.environ.get("TELEGRAM_ADMIN_USER_IDS", ""))
    # Discard pending historical updates on startup; subsequent batches
    # advance monotonically so a command is never processed twice.
    pending = _api(token, "getUpdates", {"offset": -1, "timeout": 0, "allowed_updates": ["message"]}).get("result") or []
    offset = int(pending[-1]["update_id"]) + 1 if pending else 0
    discovered: dict[str, int] = {}
    print("Listening for /topicid <canonical-key>. Press Ctrl+C to stop.")
    while True:
        data = _api(token, "getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["message"]})
        for update in data.get("result") or []:
            offset = max(offset, int(update["update_id"]) + 1)
            message = update.get("message") or {}
            text = str(message.get("text") or "").strip()
            if not text.startswith("/topicid"):
                continue
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            if chat.get("id") != expected_chat:
                continue
            if not _authorized(token, expected_chat, sender.get("id"), configured_admins):
                _reply(token, expected_chat, message, "এই command শুধু administrator ব্যবহার করতে পারবেন।")
                continue
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                _reply(token, expected_chat, message, "ব্যবহার: /topicid history")
                continue
            key = parts[1].strip().lower()
            try:
                subject = get_subject(key, require_quiz_enabled=True)
            except ValueError:
                _reply(token, expected_chat, message, "Canonical subject key সঠিক নয়।")
                continue
            thread_id = message.get("message_thread_id")
            if isinstance(thread_id, bool) or not isinstance(thread_id, int) or thread_id <= 0:
                _reply(token, expected_chat, message, "এই command একটি Telegram forum thread-এর ভিতরে পাঠান।")
                continue
            discovered[key] = thread_id
            snippet = json.dumps(discovered, ensure_ascii=False, separators=(",", ":"))
            response = (
                f"Canonical key: {key}\n"
                f"Bengali forum name: {subject.telegram_display_name}\n"
                f"Telegram chat ID: {expected_chat}\n"
                f"message_thread_id: {thread_id}\n\n"
                f"TELEGRAM_FORUM_TOPICS_JSON snippet:\n{snippet}"
            )
            _reply(token, expected_chat, message, response)


def _authorized(token: str, chat_id: int, user_id, configured: set[int]) -> bool:
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return False
    if configured:
        return user_id in configured
    result = _api(token, "getChatMember", {"chat_id": chat_id, "user_id": user_id}).get("result") or {}
    return result.get("status") in {"creator", "administrator"}


def _reply(token: str, chat_id: int, message: dict, text: str) -> None:
    payload = {"chat_id": chat_id, "text": text}
    thread_id = message.get("message_thread_id")
    if isinstance(thread_id, int) and not isinstance(thread_id, bool) and thread_id > 0:
        payload["message_thread_id"] = thread_id
    _api(token, "sendMessage", payload)


def _api(token: str, method: str, payload: dict) -> dict:
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=40)
    except requests.RequestException:
        raise RuntimeError(f"Telegram {method} network request failed.") from None
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram {method} failed with status {response.status_code}.") from exc
    if not response.ok or not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed with status {response.status_code}.")
    return data


def _admin_ids(raw: str) -> set[int]:
    result = set()
    for value in raw.split(","):
        if value.strip():
            try:
                result.add(int(value.strip()))
            except ValueError as exc:
                raise RuntimeError("TELEGRAM_ADMIN_USER_IDS must contain comma-separated integers.") from exc
    return result


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
