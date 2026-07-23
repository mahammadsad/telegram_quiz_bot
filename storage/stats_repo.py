"""Read-only analytics helpers built from the shared raw tables."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import Row, as_row

LEADERBOARD_TYPES = {
    "overall_rank",
    "daily_accuracy",
    "weekly_accuracy",
    "monthly_accuracy",
    "subject_accuracy",
    "improvement",
    "consistency",
    "revision_completion",
}


def leaderboard(limit: int = 20, offset: int = 0) -> Row:
    result = get_client().rpc(
        "get_global_leaderboard_page",
        {"p_limit": limit, "p_offset": offset},
    ).execute()
    if result.data is None:
        return {"participants": 0, "rows": [], "limit": limit, "offset": offset}
    return as_row(result.data, "global leaderboard")


def quiz_leaderboard(quiz_id: str, limit: int = 20, offset: int = 0) -> Row:
    result = get_client().rpc(
        "get_quiz_leaderboard_page",
        {"p_quiz_id": quiz_id, "p_limit": limit, "p_offset": offset},
    ).execute()
    if result.data is None:
        return {
            "quiz_id": quiz_id,
            "participants": 0,
            "rows": [],
            "limit": limit,
            "offset": offset,
        }
    return as_row(result.data, "quiz leaderboard")


def quiz_leaderboard_for_user(
    quiz_id: str,
    *,
    user_id: str | None,
    limit: int = 10,
) -> Row:
    result = get_client().rpc(
        "get_quiz_leaderboard_for_user",
        {
            "p_quiz_id": quiz_id,
            "p_user_id": user_id,
            "p_limit": limit,
        },
    ).execute()
    return as_row(result.data, "current-user quiz leaderboard")


def typed_leaderboard(
    board_type: str,
    *,
    subject_key: str | None,
    limit: int = 20,
    offset: int = 0,
) -> Row:
    clean_type = board_type.strip().lower()
    if clean_type not in LEADERBOARD_TYPES:
        raise ValueError("Unknown leaderboard type.")
    if clean_type == "subject_accuracy" and not subject_key:
        raise ValueError("Subject leaderboard requires a subject.")
    result = get_client().rpc(
        "get_leaderboard_page",
        {
            "p_type": clean_type,
            "p_subject_key": subject_key,
            "p_limit": limit,
            "p_offset": offset,
        },
    ).execute()
    if result.data is None:
        return {
        "type": clean_type,
        "subjectKey": subject_key,
        "participants": 0,
        "rows": [],
        "limit": limit,
        "offset": offset,
        }
    return as_row(result.data, "typed leaderboard")


def typed_leaderboard_for_user(
    board_type: str,
    *,
    subject_key: str | None,
    user_id: str | None,
    limit: int = 20,
    offset: int = 0,
) -> Row:
    clean_type = board_type.strip().lower()
    if clean_type not in LEADERBOARD_TYPES:
        raise ValueError("Unknown leaderboard type.")
    if clean_type == "subject_accuracy" and not subject_key:
        raise ValueError("Subject leaderboard requires a subject.")
    result = get_client().rpc(
        "get_leaderboard_for_user",
        {
            "p_type": clean_type,
            "p_subject_key": subject_key,
            "p_user_id": user_id,
            "p_limit": limit,
            "p_offset": offset,
        },
    ).execute()
    return as_row(result.data, "current-user typed leaderboard")
