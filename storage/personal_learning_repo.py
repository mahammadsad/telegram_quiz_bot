"""Service-role-only persistence for personalized learning features."""

from __future__ import annotations

from typing import Any

from database.client import get_client
from errors import DatabaseIntegrityError


def dashboard(user_id: str) -> dict:
    return _rpc("get_user_learning_dashboard", {"p_user_id": user_id})


def due_reviews(user_id: str, *, limit: int, offset: int) -> dict:
    return _rpc(
        "get_user_due_reviews",
        {"p_user_id": user_id, "p_limit": limit, "p_offset": offset},
    )


def wrong_questions(
    user_id: str,
    *,
    subject_key: str | None,
    limit: int,
    offset: int,
) -> dict:
    return _rpc(
        "get_user_wrong_questions",
        {
            "p_user_id": user_id,
            "p_subject_key": subject_key,
            "p_limit": limit,
            "p_offset": offset,
        },
    )


def submit_practice_answer(
    user_id: str,
    *,
    question_id: str,
    selected_option: int,
    source_type: str,
    response_time_seconds: float | None,
    marked_for_review: bool,
) -> dict:
    return _rpc(
        "submit_personal_practice_answer",
        {
            "p_user_id": user_id,
            "p_question_id": question_id,
            "p_selected_option": selected_option,
            "p_source_type": source_type,
            "p_response_time_seconds": response_time_seconds,
            "p_marked_for_review": marked_for_review,
        },
    )


def bookmarks(user_id: str) -> dict:
    return _rpc("get_user_bookmarks", {"p_user_id": user_id})


def set_bookmark(user_id: str, *, item_type: str, item_id: str, active: bool) -> dict:
    return _rpc(
        "set_user_bookmark",
        {
            "p_user_id": user_id,
            "p_item_type": item_type,
            "p_item_id": item_id,
            "p_active": active,
        },
    )


def preferences(user_id: str) -> dict:
    return _rpc("get_user_preferences", {"p_user_id": user_id})


def save_preferences(user_id: str, payload: dict[str, Any]) -> dict:
    return _rpc(
        "save_user_preferences",
        {
            "p_user_id": user_id,
            "p_target_exams": payload["target_exams"],
            "p_preferred_subjects": payload["preferred_subjects"],
            "p_daily_question_target": payload["daily_question_target"],
            "p_preferred_language": payload["preferred_language"],
            "p_difficulty_preference": payload["difficulty_preference"],
            "p_quiz_mode": payload["quiz_mode"],
            "p_leaderboard_visible": payload["leaderboard_visible"],
            "p_public_display_name": payload["public_display_name"],
            "p_username_visible": payload["username_visible"],
            "p_daily_reminder_enabled": payload["daily_reminder_enabled"],
        },
    )


def _rpc(name: str, payload: dict[str, Any]) -> dict:
    result = get_client().rpc(name, payload).execute()
    if not isinstance(result.data, dict):
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    return result.data
