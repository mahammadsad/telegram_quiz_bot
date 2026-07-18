"""Telegram Mini App initData verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int) -> dict:
    if not init_data:
        raise TelegramAuthError("Missing Telegram initData.")
    if not bot_token:
        raise TelegramAuthError("Missing TELEGRAM_BOT_TOKEN on the server.")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("Telegram initData has no hash.")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        raise TelegramAuthError("Telegram initData signature is invalid.")

    try:
        auth_date = int(pairs.get("auth_date", "0") or "0")
    except ValueError as exc:
        raise TelegramAuthError("Telegram initData auth_date is invalid.") from exc
    now = time.time()
    if auth_date <= 0 or auth_date > now + 30:
        raise TelegramAuthError("Telegram initData auth_date is invalid.")
    if max_age_seconds > 0 and now - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram initData is too old.")

    user_raw = pairs.get("user")
    if not user_raw:
        raise TelegramAuthError("Telegram initData has no user.")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise TelegramAuthError("Telegram user payload is invalid JSON.") from exc
    if not isinstance(user, dict):
        raise TelegramAuthError("Telegram user payload must be an object.")
    user_id = user.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise TelegramAuthError("Telegram user payload has no id.")
    return user
