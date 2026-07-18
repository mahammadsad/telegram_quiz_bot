"""Atomic ordered quiz-pack persistence backed by PostgreSQL RPCs."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError


def list_questions(quiz_id: str) -> list[dict]:
    result = (
        get_client()
        .table("quiz_questions")
        .select("id,quiz_id,question_id,question_order,created_at,questions(*)")
        .eq("quiz_id", quiz_id)
        .order("question_order")
        .execute()
    )
    return result.data or []


def save_atomic(
    *,
    quiz_id: str,
    worker_id: str,
    questions: list[dict],
    content_checksum: str,
    replace: bool,
) -> dict:
    result = get_client().rpc(
        "save_quiz_pack_atomic",
        {
            "p_quiz_id": quiz_id,
            "p_worker_id": worker_id,
            "p_questions": questions,
            "p_content_checksum": content_checksum,
            "p_replace": replace,
        },
    ).execute()
    data = result.data
    if not isinstance(data, dict) or int(data.get("question_count") or 0) != 10:
        raise DatabaseIntegrityError("Atomic quiz save returned an invalid result.")
    return data
