"""Completed Mini App attempt history and per-quiz leaderboard queries."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import Row, as_rows, first_row


def get(quiz_id: str, user_id: str) -> Row | None:
    """Return the user's most recent completed attempt (legacy helper)."""
    result = (
        get_client().table("quiz_submissions").select("*")
        .eq("quiz_id", quiz_id).eq("user_id", user_id)
        .order("completed_at", desc=True).limit(1).execute()
    )
    return first_row(result.data, "quiz_submissions.latest")


def get_by_attempt_id(quiz_id: str, user_id: str, client_attempt_id: str) -> Row | None:
    """Return one intentional attempt so HTTP retries stay idempotent."""
    result = (
        get_client().table("quiz_submissions").select("*")
        .eq("quiz_id", quiz_id).eq("user_id", user_id)
        .eq("client_attempt_id", client_attempt_id).limit(1).execute()
    )
    return first_row(result.data, "quiz_submissions.by_attempt")


def insert(payload: Row) -> Row:
    result = get_client().table("quiz_submissions").insert(payload).execute()
    row = first_row(result.data, "quiz_submissions.insert")
    if row is None:
        raise RuntimeError("quiz_submissions.insert returned no row")
    return row


def list_for_quiz(quiz_id: str, limit: int = 100) -> list[Row]:
    result = (
        get_client().table("quiz_submissions")
        .select("quiz_id,user_id,score,total,answered,client_attempt_id,completed_at,users(telegram_id,username,first_name,last_name)")
        .eq("quiz_id", quiz_id)
        .order("completed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return as_rows(result.data, "quiz_submissions.list")
