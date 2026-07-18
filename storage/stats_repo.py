"""Read-only analytics helpers built from the shared raw tables."""

from __future__ import annotations

from database.client import get_client


def leaderboard(limit: int = 20, offset: int = 0) -> dict:
    result = get_client().rpc(
        "get_global_leaderboard_page",
        {"p_limit": limit, "p_offset": offset},
    ).execute()
    return result.data or {"participants": 0, "rows": [], "limit": limit, "offset": offset}


def quiz_leaderboard(quiz_id: str, limit: int = 20, offset: int = 0) -> dict:
    result = get_client().rpc(
        "get_quiz_leaderboard_page",
        {"p_quiz_id": quiz_id, "p_limit": limit, "p_offset": offset},
    ).execute()
    return result.data or {
        "quiz_id": quiz_id,
        "participants": 0,
        "rows": [],
        "limit": limit,
        "offset": offset,
    }
