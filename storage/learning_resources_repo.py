"""Server-only reads for cached, approved quiz learning resources."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import Row, as_rows


def list_for_quiz(quiz_id: str, *, limit_per_language: int = 3) -> list[Row]:
    result = get_client().rpc(
        "get_quiz_learning_resources",
        {
            "p_quiz_id": quiz_id,
            "p_limit_per_language": max(1, min(limit_per_language, 3)),
        },
    ).execute()
    return as_rows(result.data, "quiz learning resources")
