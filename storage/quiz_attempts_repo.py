"""Transactional Mini App attempt persistence."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError


def submit_atomic(
    *,
    quiz_id: str,
    user_id: str,
    client_attempt_id: str,
    answers: list[int | None],
    duration_seconds: int | None = None,
    response_times: list[float | None] | None = None,
    marked_for_review: list[bool] | None = None,
) -> dict:
    result = get_client().rpc(
        "submit_quiz_attempt_atomic",
        {
            "p_quiz_id": quiz_id,
            "p_user_id": user_id,
            "p_client_attempt_id": client_attempt_id,
            "p_answers": answers,
            "p_duration_seconds": duration_seconds,
            "p_response_times": response_times,
            "p_marked_for_review": marked_for_review,
        },
    ).execute()
    if not isinstance(result.data, dict) or "score" not in result.data:
        raise DatabaseIntegrityError("Atomic attempt submission returned an invalid result.")
    return result.data
