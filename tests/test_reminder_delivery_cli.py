from __future__ import annotations

import pytest

from scripts import run_reminder_delivery_worker as worker
from services.reminder_delivery_service import ReminderSendError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_telegram_canary_sender_returns_only_the_numeric_receipt(monkeypatch) -> None:
    captured: dict = {}

    def post(url: str, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse(200, {"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(worker.requests, "post", post)
    assert worker._send_telegram_message(token="secret", chat_id=123, text="safe") == 42
    assert captured["json"] == {
        "chat_id": 123,
        "text": "safe",
        "disable_web_page_preview": True,
    }
    assert captured["timeout"] == 20


@pytest.mark.parametrize(
    ("status", "payload", "code", "retryable"),
    [
        (429, {"description": "retry", "parameters": {"retry_after": 70}}, "telegram_rate_limited", True),
        (403, {"description": "bot was blocked by the user"}, "telegram_blocked", False),
        (403, {"description": "user is deactivated"}, "user_deactivated", False),
        (400, {"description": "Bad Request: chat not found"}, "chat_not_found", False),
        (503, {"description": "unavailable"}, "telegram_unavailable", True),
    ],
)
def test_telegram_canary_sender_classifies_safe_completion_outcomes(
    monkeypatch, status: int, payload: dict, code: str, retryable: bool
) -> None:
    monkeypatch.setattr(
        worker.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse(status, payload),
    )
    with pytest.raises(ReminderSendError) as raised:
        worker._send_telegram_message(token="secret", chat_id=123, text="safe")
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    if status == 429:
        assert raised.value.retry_after_seconds == 70
