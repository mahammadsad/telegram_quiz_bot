from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from services.reminder_delivery_service import (
    SYNTHETIC_MESSAGE,
    ReminderSendError,
    run_reminder_delivery_batch,
)

USER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_USER_ID = "22222222-2222-4222-8222-222222222222"


class FakeRepository:
    def __init__(self, items: list[dict[str, Any]] | None = None) -> None:
        self.items = items or []
        self.completed: list[dict[str, Any]] = []
        self.claims = 0

    def get_contract(self) -> dict[str, Any]:
        return {"ready": True, "answerFreePayload": True, "deliveryEnabled": False}

    def claim_due(self, *, worker_id: str, limit: int) -> list[dict[str, Any]]:
        self.claims += 1
        return self.items[:limit]

    def telegram_chat_id_for_user(self, user_id: str) -> int | None:
        return 123456 if user_id == USER_ID else None

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.completed.append(kwargs)
        return {"state": kwargs["outcome"]}


def _item(*, user_id: str = USER_ID, kind: str = "synthetic_canary") -> dict[str, Any]:
    return {
        "deliveryId": str(UUID(int=3)),
        "userId": user_id,
        "reminderKind": kind,
    }


def test_disabled_worker_never_reads_or_claims_delivery_state() -> None:
    repository = FakeRepository([_item()])
    result = run_reminder_delivery_batch(
        mode="disabled",
        worker_id="worker",
        expected_synthetic_user_id=None,
        send_message=lambda _chat, _text: 1,
        repository=repository,
    )
    assert result.as_dict() == {
        "mode": "disabled", "claimed": 0, "sent": 0,
        "retrying": 0, "failed": 0, "cancelled": 0,
    }
    assert repository.claims == 0


def test_synthetic_worker_sends_only_answer_free_canary_and_records_receipt() -> None:
    repository = FakeRepository([_item()])
    sends: list[tuple[int, str]] = []
    result = run_reminder_delivery_batch(
        mode="synthetic",
        worker_id="worker",
        expected_synthetic_user_id=USER_ID,
        send_message=lambda chat, text: sends.append((chat, text)) or 987,
        repository=repository,
    )
    assert result.sent == 1
    assert sends == [(123456, SYNTHETIC_MESSAGE)]
    assert "উত্তর" in SYNTHETIC_MESSAGE
    assert "score" not in SYNTHETIC_MESSAGE.casefold()
    assert repository.completed == [{
        "delivery_id": str(UUID(int=3)),
        "worker_id": "worker",
        "outcome": "sent",
        "telegram_message_id": 987,
    }]


@pytest.mark.parametrize(
    ("item", "failure_code"),
    [
        (_item(kind="daily_study"), "delivery_mode_disabled"),
        (_item(user_id=OTHER_USER_ID), "synthetic_scope_mismatch"),
    ],
)
def test_synthetic_worker_cancels_any_item_outside_exact_canary_scope(
    item: dict[str, Any], failure_code: str
) -> None:
    repository = FakeRepository([item])
    result = run_reminder_delivery_batch(
        mode="synthetic",
        worker_id="worker",
        expected_synthetic_user_id=USER_ID,
        send_message=lambda _chat, _text: pytest.fail("must not send"),
        repository=repository,
    )
    assert result.cancelled == 1
    assert repository.completed[0]["outcome"] == "cancelled"
    assert repository.completed[0]["failure_code"] == failure_code


def test_retryable_send_failure_uses_bounded_database_retry() -> None:
    repository = FakeRepository([_item()])

    def fail(_chat: int, _text: str) -> int:
        raise ReminderSendError(
            "telegram_rate_limited", retryable=True, retry_after_seconds=999999
        )

    result = run_reminder_delivery_batch(
        mode="synthetic",
        worker_id="worker",
        expected_synthetic_user_id=USER_ID,
        send_message=fail,
        repository=repository,
    )
    assert result.retrying == 1
    assert repository.completed[0]["outcome"] == "retry_wait"
    assert repository.completed[0]["retry_after_seconds"] == 86400


def test_missing_chat_and_unknown_receipt_fail_without_retrying() -> None:
    missing = FakeRepository([_item(user_id=OTHER_USER_ID)])
    result = run_reminder_delivery_batch(
        mode="synthetic",
        worker_id="worker",
        expected_synthetic_user_id=OTHER_USER_ID,
        send_message=lambda _chat, _text: 1,
        repository=missing,
    )
    assert result.failed == 1
    assert missing.completed[0]["failure_code"] == "chat_not_found"

    unknown = FakeRepository([_item()])
    result = run_reminder_delivery_batch(
        mode="synthetic",
        worker_id="worker",
        expected_synthetic_user_id=USER_ID,
        send_message=lambda _chat, _text: 0,
        repository=unknown,
    )
    assert result.failed == 1
    assert unknown.completed[0]["failure_code"] == "delivery_unknown"
