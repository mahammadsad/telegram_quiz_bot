"""Private repository for the disabled-by-default reminder delivery contract."""

from __future__ import annotations

from typing import Any

from database.client import get_client
from storage.contracts import Row, as_row, as_rows, first_row


def get_contract() -> Row:
    result = get_client().rpc("get_reminder_delivery_contract", {}).execute()
    return as_row(result.data, "reminder_delivery.contract")


def claim_due(*, worker_id: str, limit: int) -> list[Row]:
    result = get_client().rpc(
        "claim_due_learner_reminders",
        {"p_worker_id": worker_id, "p_limit": limit},
    ).execute()
    payload = as_row(result.data, "reminder_delivery.claim")
    return as_rows(payload.get("items"), "reminder_delivery.claim.items")


def complete(
    *,
    delivery_id: str,
    worker_id: str,
    outcome: str,
    telegram_message_id: int | None = None,
    failure_code: str | None = None,
    retry_after_seconds: int | None = None,
) -> Row:
    result = get_client().rpc(
        "complete_learner_reminder_delivery",
        {
            "p_delivery_id": delivery_id,
            "p_worker_id": worker_id,
            "p_outcome": outcome,
            "p_telegram_message_id": telegram_message_id,
            "p_failure_code": failure_code,
            "p_retry_after_seconds": retry_after_seconds,
        },
    ).execute()
    return as_row(result.data, "reminder_delivery.complete")


def telegram_chat_id_for_user(user_id: str) -> int | None:
    result = (
        get_client()
        .table("users")
        .select("telegram_id")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    row = first_row(result.data, "reminder_delivery.user")
    if row is None:
        return None
    value: Any = row.get("telegram_id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RuntimeError("Reminder recipient has an invalid Telegram identifier.")
    try:
        chat_id = int(value)
    except ValueError as exc:
        raise RuntimeError("Reminder recipient has an invalid Telegram identifier.") from exc
    return chat_id if chat_id > 0 else None
