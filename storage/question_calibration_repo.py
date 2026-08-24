"""Bounded, read-only evidence retrieval for question calibration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.client import get_client
from storage.contracts import Row, as_rows

PAGE_SIZE = 1000
MAX_ROWS = 50_000


def list_first_attempt_observations(*, since: datetime, max_rows: int = MAX_ROWS) -> list[Row]:
    """Return first completed assessment observations within strict bounds."""
    bounded_max = max(1, min(max_rows, MAX_ROWS))
    rows: list[Row] = []
    for offset in range(0, bounded_max, PAGE_SIZE):
        page_size = min(PAGE_SIZE, bounded_max - offset)
        result = (
            get_client()
            .table("quiz_attempt_answers")
            .select(
                "attempt_id,question_id,selected_option,correct_option,is_correct,"
                "quiz_attempts!inner(user_id,score,total,attempt_number,is_completed,completed_at),"
                "questions!inner(subject,difficulty)"
            )
            .eq("quiz_attempts.attempt_number", 1)
            .eq("quiz_attempts.is_completed", True)
            .gte("quiz_attempts.completed_at", since.isoformat())
            .order("created_at")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = as_rows(result.data, "question calibration observations")
        rows.extend(_flatten(row) for row in page)
        if len(page) < page_size:
            break
    return rows


def _flatten(row: Row) -> Row:
    attempt = _relation(row.get("quiz_attempts"))
    question = _relation(row.get("questions"))
    return {
        "attempt_id": row.get("attempt_id"),
        "question_id": row.get("question_id"),
        "selected_option": row.get("selected_option"),
        "correct_option": row.get("correct_option"),
        "is_correct": row.get("is_correct"),
        "user_id": attempt.get("user_id"),
        "score": attempt.get("score"),
        "total": attempt.get("total"),
        "completed_at": attempt.get("completed_at"),
        "subject": question.get("subject"),
        "authored_difficulty": question.get("difficulty"),
    }


def _relation(value: Any) -> Row:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}
