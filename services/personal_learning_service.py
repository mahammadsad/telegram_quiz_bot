"""Authenticated personalized-learning orchestration and public projections."""

from __future__ import annotations

import uuid
from datetime import date
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
# The learner interface is Bengali-complete only. Content records and PYQ
# filters may legitimately carry other languages, but a saved UI preference
# must not claim a locale the application cannot render end to end.
SUPPORTED_UI_LANGUAGES = {"bn"}
DIFFICULTIES = {"adaptive", "easy", "medium", "hard"}
QUIZ_MODES = {"timed", "practice"}
BOOKMARK_TYPES = {"question", "resource"}
PRACTICE_SOURCES = {"wrong", "due", "bookmark", "weak_topic"}
MASTERY_STRENGTHS = {"all", "due", "weak", "strong"}


def dashboard(telegram_user: dict) -> dict:
    user_id = _user_id(telegram_user)
    payload = _safe(personal_learning_repo.dashboard(user_id))
    preference_payload = _safe(personal_learning_repo.preferences(user_id))
    payload["studyPlan"] = _study_plan(payload, preference_payload)
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


def knowledge_reviews(telegram_user: dict, *, limit: int, offset: int) -> dict:
    return _safe(
        personal_learning_repo.knowledge_reviews(
            _user_id(telegram_user),
            limit=_page_limit(limit),
            offset=max(0, offset),
        )
    )


def daily_rollups(
    telegram_user: dict,
    *,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> dict:
    if date_from and date_to and date_from > date_to:
        raise ValueError("Start date must not be after end date.")
    return _safe(
        personal_learning_repo.daily_rollups(
            _user_id(telegram_user),
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            limit=_page_limit(limit),
            offset=max(0, offset),
        )
    )


def knowledge_mastery(
    telegram_user: dict,
    *,
    subject_key: str | None,
    strength: str,
    limit: int,
    offset: int,
) -> dict:
    clean_subject = subject_key.strip() if subject_key else None
    if clean_subject and clean_subject not in SUBJECTS:
        raise ValueError("Unknown subject key.")
    if strength not in MASTERY_STRENGTHS:
        raise ValueError("Unknown mastery strength filter.")
    return _safe(
        personal_learning_repo.knowledge_mastery(
            _user_id(telegram_user),
            subject_key=clean_subject,
            strength=strength,
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
    payload = _safe(personal_learning_repo.bookmarks(_user_id(telegram_user)))
    return {
        **payload,
        "mode": "practice",
        "sourceType": "bookmark",
    }


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
    if language not in SUPPORTED_UI_LANGUAGES:
        raise ValueError("Preferred interface language is not fully supported.")
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


def _study_plan(dashboard_payload: dict, preference_payload: dict) -> dict:
    """Build one transparent next assignment from saved preferences and mastery."""
    preferred_subjects = [
        str(value)
        for value in preference_payload.get("preferredSubjects", [])
        if str(value) in SUBJECTS
    ]
    target_exams = [
        str(value)
        for value in preference_payload.get("targetExams", [])
        if str(value) in EXAM_KEYS
    ]
    daily_target = _bounded_int(
        preference_payload.get("dailyQuestionTarget", dashboard_payload.get("dailyTarget", 30)),
        default=30,
        minimum=1,
        maximum=130,
    )
    answered = _bounded_int(
        dashboard_payload.get("todayAnswered", 0), default=0, minimum=0, maximum=10000
    )
    remaining = max(0, daily_target - answered)
    due = _bounded_int(
        dashboard_payload.get("revisionDueToday", dashboard_payload.get("dueReviews", 0)),
        default=0,
        minimum=0,
        maximum=10000,
    )
    weak = _bounded_int(
        dashboard_payload.get("weakQuestions", 0), default=0, minimum=0, maximum=10000
    )
    due_subject = _priority_subject(
        dashboard_payload.get("subjectRevisionCounts"), preferred_subjects, value_key="due"
    )
    weak_subject = _priority_subject(
        dashboard_payload.get("subjectPerformance"),
        preferred_subjects,
        value_key="accuracy",
        lowest=True,
    )
    if not weak_subject:
        candidate = dashboard_payload.get("weakestSubject")
        if isinstance(candidate, dict) and str(candidate.get("subjectKey") or "") in SUBJECTS:
            weak_subject = str(candidate["subjectKey"])

    action = "broad_maintenance"
    subject_key: str | None = None
    exam_key: str | None = None
    reason_code = "broad_maintenance"
    question_target = max(1, remaining) if remaining else 0
    if due > 0:
        action = "continue_due_revision"
        subject_key = due_subject
        reason_code = "preferred_subject_due" if due_subject in preferred_subjects else "due_review"
        question_target = min(due, max(1, remaining or due))
    elif weak > 0:
        action = "practice_weak_topics"
        subject_key = weak_subject
        reason_code = (
            "preferred_subject_weakness"
            if weak_subject in preferred_subjects
            else "weakest_available_subject"
        )
        question_target = min(weak, max(1, remaining or weak))
    elif remaining == 0:
        action = "goal_complete"
        reason_code = "daily_target_complete"
    elif target_exams:
        action = "target_exam_mock"
        exam_key = target_exams[0]
        reason_code = "saved_target_exam"
    elif preferred_subjects:
        action = "preferred_subject_quiz"
        subject_key = preferred_subjects[0]
        reason_code = "saved_preferred_subject"

    return {
        "version": 1,
        "personalized": bool(preferred_subjects or target_exams),
        "preferredSubjects": preferred_subjects,
        "targetExams": target_exams,
        "dailyQuestionTarget": daily_target,
        "remainingQuestions": remaining,
        "questionTarget": question_target,
        "nextAction": action,
        "subjectKey": subject_key,
        "examKey": exam_key,
        "reasonCode": reason_code,
        "broadcastQuizPersonalized": False,
    }


def _priority_subject(
    rows: Any,
    preferred_subjects: list[str],
    *,
    value_key: str,
    lowest: bool = False,
) -> str | None:
    if not isinstance(rows, list):
        return None
    valid = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("subjectKey") or "") in SUBJECTS
    ]
    preferred = [row for row in valid if str(row["subjectKey"]) in preferred_subjects]
    candidates = preferred or valid
    if not candidates:
        return None

    def score(row: dict) -> float:
        value = row.get(value_key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    selected = min(candidates, key=score) if lowest else max(candidates, key=score)
    return str(selected["subjectKey"])


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(minimum, min(int(value), maximum))


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
