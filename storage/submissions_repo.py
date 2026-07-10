"""Completed Mini App attempt history and per-quiz leaderboard queries."""

from __future__ import annotations

from database.client import get_client


def get(quiz_id: str, user_id: str) -> dict | None:
    """Return the user's most recent completed attempt (legacy helper)."""
    result = (
        get_client().table("quiz_submissions").select("*")
        .eq("quiz_id", quiz_id).eq("user_id", user_id)
        .order("completed_at", desc=True).limit(1).execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_by_attempt_id(quiz_id: str, user_id: str, client_attempt_id: str) -> dict | None:
    """Return one intentional attempt so HTTP retries stay idempotent."""
    result = (
        get_client().table("quiz_submissions").select("*")
        .eq("quiz_id", quiz_id).eq("user_id", user_id)
        .eq("client_attempt_id", client_attempt_id).limit(1).execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def insert(payload: dict) -> dict:
    result = get_client().table("quiz_submissions").insert(payload).execute()
    return result.data[0]


def list_for_quiz(quiz_id: str, limit: int = 100) -> list[dict]:
    result = (
        get_client().table("quiz_submissions")
        .select("quiz_id,user_id,score,total,answered,client_attempt_id,completed_at,users(telegram_id,username,first_name,last_name)")
        .eq("quiz_id", quiz_id)
        .order("completed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
