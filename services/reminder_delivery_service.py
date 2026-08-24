"""Fail-closed, answer-free processing for synthetic reminder canaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol
from uuid import UUID

from storage import reminder_delivery_repo
from storage.contracts import Row

SYNTHETIC_MESSAGE = (
    "🧪 Citizen Affairs স্মরণবার্তা পরীক্ষা\n\n"
    "এটি শুধু একটি synthetic delivery test। এতে কোনো উত্তর, স্কোর বা ব্যক্তিগত "
    "পারফরম্যান্স তথ্য নেই।\n\n"
    "Citizen Affairs বাংলা: https://citizenaffairs.in/bn/"
)


class ReminderRepository(Protocol):
    def get_contract(self) -> Row: ...
    def claim_due(self, *, worker_id: str, limit: int) -> list[Row]: ...
    def telegram_chat_id_for_user(self, user_id: str) -> int | None: ...
    def complete(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        outcome: str,
        telegram_message_id: int | None = None,
        failure_code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> Row: ...


class ReminderSendError(RuntimeError):
    """A privacy-safe, classified Telegram delivery failure."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class ReminderBatchResult:
    mode: str
    claimed: int = 0
    sent: int = 0
    retrying: int = 0
    failed: int = 0
    cancelled: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "mode": self.mode,
            "claimed": self.claimed,
            "sent": self.sent,
            "retrying": self.retrying,
            "failed": self.failed,
            "cancelled": self.cancelled,
        }


def run_reminder_delivery_batch(
    *,
    mode: str,
    worker_id: str,
    expected_synthetic_user_id: str | None,
    send_message: Callable[[int, str], int],
    repository: ReminderRepository = reminder_delivery_repo,
    limit: int = 25,
) -> ReminderBatchResult:
    """Process a bounded batch; only an explicitly scoped canary may be sent."""
    if mode == "disabled":
        return ReminderBatchResult(mode=mode)
    if mode != "synthetic":
        raise ValueError("Reminder delivery mode must be disabled or synthetic.")
    if not worker_id.strip() or len(worker_id) > 80:
        raise ValueError("A bounded reminder worker ID is required.")
    if limit not in range(1, 26):
        raise ValueError("Reminder claim limit must be between 1 and 25.")
    expected_user_id = _uuid(expected_synthetic_user_id, "Synthetic canary user ID")

    contract = repository.get_contract()
    if contract.get("ready") is not True or contract.get("answerFreePayload") is not True:
        raise RuntimeError("Reminder delivery contract is not ready and answer-free.")
    if contract.get("deliveryEnabled") is not False:
        raise RuntimeError("Synthetic worker refuses a contract with real delivery enabled.")

    items = repository.claim_due(worker_id=worker_id, limit=limit)
    counts = {"sent": 0, "retrying": 0, "failed": 0, "cancelled": 0}
    for item in items:
        delivery_id = _uuid(item.get("deliveryId"), "Delivery ID")
        user_id = _uuid(item.get("userId"), "Reminder user ID")
        if item.get("reminderKind") != "synthetic_canary":
            repository.complete(
                delivery_id=delivery_id,
                worker_id=worker_id,
                outcome="cancelled",
                failure_code="delivery_mode_disabled",
            )
            counts["cancelled"] += 1
            continue
        if user_id != expected_user_id:
            repository.complete(
                delivery_id=delivery_id,
                worker_id=worker_id,
                outcome="cancelled",
                failure_code="synthetic_scope_mismatch",
            )
            counts["cancelled"] += 1
            continue

        chat_id = repository.telegram_chat_id_for_user(user_id)
        if chat_id is None:
            repository.complete(
                delivery_id=delivery_id,
                worker_id=worker_id,
                outcome="failed",
                failure_code="chat_not_found",
            )
            counts["failed"] += 1
            continue
        try:
            message_id = send_message(chat_id, SYNTHETIC_MESSAGE)
            if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                raise ReminderSendError("delivery_unknown", retryable=False)
        except ReminderSendError as exc:
            if exc.retryable:
                repository.complete(
                    delivery_id=delivery_id,
                    worker_id=worker_id,
                    outcome="retry_wait",
                    failure_code=exc.code,
                    retry_after_seconds=_retry_delay(exc.retry_after_seconds),
                )
                counts["retrying"] += 1
            else:
                repository.complete(
                    delivery_id=delivery_id,
                    worker_id=worker_id,
                    outcome="failed",
                    failure_code=exc.code,
                )
                counts["failed"] += 1
            continue

        repository.complete(
            delivery_id=delivery_id,
            worker_id=worker_id,
            outcome="sent",
            telegram_message_id=message_id,
        )
        counts["sent"] += 1

    return ReminderBatchResult(mode=mode, claimed=len(items), **counts)


def _uuid(value: object, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID.") from exc


def _retry_delay(value: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 60
    return max(30, min(value, 86400))
