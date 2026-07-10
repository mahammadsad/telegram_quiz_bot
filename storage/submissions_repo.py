"""Immutable completed Mini App submissions and per-quiz leaderboard queries."""

from __future__ import annotations

from database.client import get_client


def get(quiz_id: str, user_id: str) -> dict | None:
    result = (
        get_client().table("quiz_submissions").select("*")
        .eq("quiz_id", quiz_id).eq("user_id", user_id).limit(1).execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def insert(payload: dict) -> dict:
    result = get_client().table("quiz_submissions").insert(payload).execute()
    return result.data[0]


def list_for_quiz(quiz_id: str, limit: int = 100) -> list[dict]:
    result = (
        get_client().table("quiz_submissions")
        .select("quiz_id,user_id,score,total,answered,completed_at,users(telegram_id,username,first_name,last_name)")
        .eq("quiz_id", quiz_id)
        .order("score", desc=True)
        .order("completed_at")
        .limit(limit)
        .execute()
    )
    return result.data or []
