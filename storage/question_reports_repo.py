"""Authenticated question-report moderation RPC adapter."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError


def submit(
    *,
    question_id: str,
    quiz_id: str,
    user_id: str,
    client_attempt_id: str,
    reason: str,
    details: str,
    threshold: int,
) -> dict:
    try:
        result = get_client().rpc(
            "submit_question_report",
            {
                "p_question_id": question_id,
                "p_quiz_id": quiz_id,
                "p_user_id": user_id,
                "p_client_attempt_id": client_attempt_id,
                "p_reason": reason,
                "p_details": details or None,
                "p_threshold": threshold,
            },
        ).execute()
    except Exception as exc:
        message = str(exc).lower()
        safe_errors = (
            "already reported",
            "report rate limit exceeded",
            "not linked to this completed attempt",
        )
        for safe_error in safe_errors:
            if safe_error in message:
                raise ValueError(safe_error) from exc
        raise
    if not isinstance(result.data, dict) or result.data.get("status") != "accepted":
        raise DatabaseIntegrityError("Question report RPC returned an invalid result.")
    return result.data
