from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from telegram.auth import TelegramAuthError, verify_init_data

TEST_BOT_VALUE = "123:secret"


def signed_init_data(*, auth_date: int | None = None, include_user: bool = True) -> str:
    pairs = {"auth_date": str(auth_date or int(time.time())), "query_id": "query-1"}
    if include_user:
        pairs["user"] = json.dumps({"id": 42, "first_name": "Test"}, separators=(",", ":"))
    check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", TEST_BOT_VALUE.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_valid_init_data_returns_verified_user():
    assert verify_init_data(signed_init_data(), TEST_BOT_VALUE, 3600)["id"] == 42


def test_invalid_signature_is_rejected():
    with pytest.raises(TelegramAuthError, match="signature"):
        verify_init_data(signed_init_data().replace("query-1", "query-2"), TEST_BOT_VALUE, 3600)


def test_expired_init_data_is_rejected():
    with pytest.raises(TelegramAuthError, match="too old"):
        verify_init_data(signed_init_data(auth_date=int(time.time()) - 7200), TEST_BOT_VALUE, 60)


def test_future_init_data_is_rejected():
    with pytest.raises(TelegramAuthError, match="auth_date"):
        verify_init_data(signed_init_data(auth_date=int(time.time()) + 300), TEST_BOT_VALUE, 3600)


@pytest.mark.parametrize(
    ("payload", "message"),
    [("auth_date=1", "no hash"), (signed_init_data(include_user=False), "no user")],
)
def test_required_auth_fields_are_enforced(payload, message):
    with pytest.raises(TelegramAuthError, match=message):
        verify_init_data(payload, TEST_BOT_VALUE, 0)


def test_missing_bot_token_is_rejected():
    with pytest.raises(TelegramAuthError, match="TELEGRAM_BOT_TOKEN"):
        verify_init_data(signed_init_data(), "", 3600)
