"""Authenticated personalized-learning orchestration and public projections."""

from __future__ import annotations

import uuid
from typing import Any

from config.settings import QUESTION_REPORT_THRESHOLD
from config.subjects import SUBJECTS
from models.user import User
from services.quiz_pack_service import REPORT_REASONS
from storage import personal_learning_repo, question_reports_repo, users_repo

EXAM_KEYS = {
    "WBCS",
    "WBPSC_CLERKSHIP",
    "WBPSC_MISC",
    "WBP_CONSTABLE",
    "WBP_SI",
    "KOLKATA_POLICE",
    "PRIMARY_TET",
    "UPPER_PRIMARY_TET",
    "SSC",
    "RAILWAY",
    "BANKING",
}
LANGUAGES = {"bn", "hi", "en"}
DIFFICULTIES = {"adaptive", "easy", "medium", "hard"}
QUIZ_MODES = {"timed", "practice"}
BOOKMARK_TYPES = {"question", "resource"}
PRACTICE_SOURCES = {"wrong", "due", "bookmark", "weak_topic"}


def dashboard(telegram_user: dict) -> dict:
    payload = _safe(personal_learning_repo.dashboard(_user_id(telegram_user)))
    payload["identity"] = _identity(telegram_user)
    return payload


def due_reviews(telegram_user: dict, *, limit: int, offset: int) -> dict:
    return _safe(
        personal_learning_repo.due_reviews(
            _user_id(telegram_user),
            limit=_page_limit(limit),
            offset=max(0, offset),
        )
    )


def wrong_questions(
    telegram_user: dict,
    *,
    subject_key: str | None,
    limit: int,
    offset: int,
) -> dict:
    clean_subject = subject_key.strip() if subject_key else None
    if clean_subject and clean_subject not in SUBJECTS:
        raise ValueError("Unknown subject key.")
    return _safe(
        personal_learning_repo.wrong_questions(
            _user_id(telegram_user),
            subject_key=clean_subject,
            limit=_page_limit(limit),
            offset=max(0, offset),
        )
    )


def submit_practice_answer(
    telegram_user: dict,
    *,
    question_id: str,
    client_attempt_id: uuid.UUID,
    selected_option: int,
    source_type: str,
    mode: str,
    response_time_seconds: float | None,
    marked_for_review: bool,
) -> dict:
    if isinstance(selected_option, bool) or selected_option not in range(4):
        raise ValueError("Selected option must be between 0 and 3.")
    if source_type not in PRACTICE_SOURCES:
        raise ValueError("Invalid practice source.")
    expected_mode = "practice" if source_type == "bookmark" else "revision"
    if mode != expected_mode:
        raise ValueError("Practice mode does not match the server-provided queue mode.")
    if response_time_seconds is not None and not 0 <= response_time_seconds <= 3600:
        raise ValueError("Invalid response time.")
    return _safe(
        personal_learning_repo.submit_practice_answer(
            _user_id(telegram_user),
            question_id=question_id,
            client_attempt_id=client_attempt_id,
            selected_option=selected_option,
            source_type=source_type,
            mode=mode,
            response_time_seconds=response_time_seconds,
            marked_for_review=marked_for_review,
        )
    )


def report_practice_question(
    telegram_user: dict,
    *,
    question_id: str,
    client_attempt_id: uuid.UUID,
    reason: str,
    details: str,
) -> dict:
    if reason not in REPORT_REASONS:
        raise ValueError("Invalid report reason.")
    clean_details = details.strip()
    if len(clean_details) > 1000:
        raise ValueError("Report details must be 1000 characters or fewer.")
    if reason == "other" and not clean_details:
        raise ValueError("Other reports require details.")
    return _safe(
        question_reports_repo.submit_practice(
            question_id=question_id,
            user_id=_user_id(telegram_user),
            client_attempt_id=str(client_attempt_id),
            reason=reason,
            details=clean_details,
            threshold=QUESTION_REPORT_THRESHOLD,
        )
    )


def bookmarks(telegram_user: dict) -> dict:
    return _safe(personal_learning_repo.bookmarks(_user_id(telegram_user)))


def set_bookmark(
    telegram_user: dict,
    *,
    item_type: str,
    item_id: str,
    active: bool,
) -> dict:
    if item_type not in BOOKMARK_TYPES:
        raise ValueError("Invalid bookmark type.")
    return _safe(
        personal_learning_repo.set_bookmark(
            _user_id(telegram_user),
            item_type=item_type,
            item_id=item_id,
            active=active,
        )
    )


def preferences(telegram_user: dict) -> dict:
    return _safe(personal_learning_repo.preferences(_user_id(telegram_user)))


def save_preferences(telegram_user: dict, payload: dict[str, Any]) -> dict:
    target_exams = _unique_strings(payload.get("target_exams"), maximum=11)
    preferred_subjects = _unique_strings(payload.get("preferred_subjects"), maximum=13)
    if not set(target_exams).issubset(EXAM_KEYS):
        raise ValueError("Unknown target exam.")
    if not set(preferred_subjects).issubset(SUBJECTS):
        raise ValueError("Unknown preferred subject.")
    language = str(payload.get("preferred_language") or "").strip()
    difficulty = str(payload.get("difficulty_preference") or "").strip()
    quiz_mode = str(payload.get("quiz_mode") or "").strip()
    if language not in LANGUAGES:
        raise ValueError("Invalid preferred language.")
    if difficulty not in DIFFICULTIES:
        raise ValueError("Invalid difficulty preference.")
    if quiz_mode not in QUIZ_MODES:
        raise ValueError("Invalid quiz mode.")
    daily_target = payload.get("daily_question_target")
    if isinstance(daily_target, bool) or not isinstance(daily_target, int) or not 1 <= daily_target <= 130:
        raise ValueError("Daily question target must be between 1 and 130.")
    display_name = str(payload.get("public_display_name") or "").strip() or None
    if display_name and not 2 <= len(display_name) <= 40:
        raise ValueError("Public display name must contain 2 to 40 characters.")
    clean = {
        "target_exams": target_exams,
        "preferred_subjects": preferred_subjects,
        "daily_question_target": daily_target,
        "preferred_language": language,
        "difficulty_preference": difficulty,
        "quiz_mode": quiz_mode,
        "leaderboard_visible": bool(payload.get("leaderboard_visible")),
        "public_display_name": display_name,
        "username_visible": bool(payload.get("username_visible")),
        "daily_reminder_enabled": bool(payload.get("daily_reminder_enabled")),
        "revision_sound_enabled": bool(payload.get("revision_sound_enabled", True)),
        "revision_vibration_enabled": bool(payload.get("revision_vibration_enabled", False)),
    }
    return _safe(personal_learning_repo.save_preferences(_user_id(telegram_user), clean))


def _user_id(telegram_user: dict) -> str:
    return str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])


def _page_limit(value: int) -> int:
    return max(1, min(value, 100))


def _unique_strings(value: Any, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Invalid preference list.")
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in cleaned:
            continue
        cleaned.append(text)
    return cleaned


def _safe(payload: dict) -> dict:
    text = str(payload).lower()
    for private_field in ("telegram_id", "correct_option", "approved_by", "verification_notes"):
        if private_field in text:
            raise ValueError("Personalized-learning projection contained a private field.")
    return payload


def _identity(telegram_user: dict) -> dict:
    first = str(telegram_user.get("first_name") or "").strip()
    last = str(telegram_user.get("last_name") or "").strip()
    username = str(telegram_user.get("username") or "").strip()
    display_name = " ".join(value for value in (first, last) if value)
    if not display_name:
        display_name = f"@{username}" if username else "শিক্ষার্থী"
    initials = "".join(value[:1] for value in (first, last) if value)[:2]
    if not initials:
        initials = display_name[:1]
    photo_url = str(telegram_user.get("photo_url") or "").strip()
    return {
        "displayName": display_name,
        "username": f"@{username}" if username else None,
        "profilePhotoUrl": photo_url if photo_url.startswith("https://") else None,
        "initials": initials.upper(),
        "isCurrentUser": True,
        "label": "এটি আপনার ড্যাশবোর্ড",
    }
