"""Run the disabled-by-default synthetic Telegram reminder worker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import require_env  # noqa: E402
from services.reminder_delivery_service import (  # noqa: E402
    ReminderSendError,
    run_reminder_delivery_batch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("disabled", "synthetic"), default="disabled")
    parser.add_argument("--worker-id", default="reminder-synthetic-worker")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--confirm-synthetic-canary", action="store_true")
    args = parser.parse_args()

    if args.mode == "synthetic" and not args.confirm_synthetic_canary:
        raise SystemExit("Synthetic mode requires --confirm-synthetic-canary.")
    expected_user_id = (
        require_env("REMINDER_SYNTHETIC_USER_ID") if args.mode == "synthetic" else None
    )
    token = require_env("TELEGRAM_BOT_TOKEN") if args.mode == "synthetic" else ""

    def send(chat_id: int, text: str) -> int:
        return _send_telegram_message(token=token, chat_id=chat_id, text=text)

    result = run_reminder_delivery_batch(
        mode=args.mode,
        worker_id=args.worker_id,
        expected_synthetic_user_id=expected_user_id,
        send_message=send,
        limit=args.limit,
    )
    print(json.dumps(result.as_dict(), sort_keys=True))
    return int(result.failed > 0 or result.cancelled > 0)


def _send_telegram_message(*, token: str, chat_id: int, text: str) -> int:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise ReminderSendError("telegram_network", retryable=True) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ReminderSendError("delivery_unknown", retryable=False) from exc
    if response.ok and payload.get("ok") is True:
        message_id = (payload.get("result") or {}).get("message_id")
        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
            return message_id
        raise ReminderSendError("delivery_unknown", retryable=False)

    description = str(payload.get("description") or "").casefold()
    if response.status_code == 429:
        retry_after = (payload.get("parameters") or {}).get("retry_after")
        raise ReminderSendError(
            "telegram_rate_limited",
            retryable=True,
            retry_after_seconds=retry_after if isinstance(retry_after, int) else 60,
        )
    if "blocked" in description:
        raise ReminderSendError("telegram_blocked", retryable=False)
    if "deactivated" in description:
        raise ReminderSendError("user_deactivated", retryable=False)
    if "chat not found" in description:
        raise ReminderSendError("chat_not_found", retryable=False)
    if response.status_code >= 500:
        raise ReminderSendError("telegram_unavailable", retryable=True)
    raise ReminderSendError("telegram_rejected", retryable=False)


if __name__ == "__main__":
    raise SystemExit(main())
