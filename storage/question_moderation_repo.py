"""Least-privilege adapters for the protected question moderation queue."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError
from storage.contracts import Row, as_row


def review_queue(*, status: str | None, limit: int, offset: int) -> Row:
    return _rpc(
        "get_question_moderation_queue",
        {"p_status": status, "p_limit": limit, "p_offset": offset},
    )


def review_case(
    case_id: str,
    *,
    decision: str,
    actor: str,
    resolution: str,
    superseding_question_id: str | None,
) -> Row:
    return _rpc(
        "review_question_moderation_case",
        {
            "p_case_id": case_id,
            "p_decision": decision,
            "p_actor": actor,
            "p_resolution": resolution,
            "p_superseding_question_id": superseding_question_id,
        },
    )


def quarantine_question(
    question_id: str,
    *,
    trigger: str,
    actor: str,
    reason: str,
    superseding_question_id: str | None,
) -> Row:
    return _rpc(
        "quarantine_question_authoritatively",
        {
            "p_question_id": question_id,
            "p_trigger": trigger,
            "p_actor": actor,
            "p_reason": reason,
            "p_superseding_question_id": superseding_question_id,
        },
    )


def _rpc(name: str, payload: dict) -> Row:
    result = get_client().rpc(name, payload).execute()
    if not isinstance(result.data, dict):
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    return as_row(result.data, name)
