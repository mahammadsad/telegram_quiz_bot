"""Authenticated orchestration for real PYQs and generalized timed tests."""

from __future__ import annotations

import uuid

from models.user import User
from storage import test_attempts_repo, users_repo

LANGUAGES = {"bn", "hi", "en", "bilingual"}


def previous_year_catalog(
    *,
    exam_key: str | None,
    exam_year: int | None,
    language: str | None,
    limit: int,
    offset: int,
) -> dict:
    clean_exam = exam_key.strip().upper() if exam_key else None
    if clean_exam and (
        len(clean_exam) > 50 or any(character.isspace() for character in clean_exam)
    ):
        raise ValueError("Invalid exam key.")
    clean_language = language.strip().lower() if language else None
    if clean_language and clean_language not in LANGUAGES:
        raise ValueError("Invalid language.")
    if exam_year is not None and not 1900 <= exam_year <= 2100:
        raise ValueError("Invalid exam year.")
    return test_attempts_repo.previous_year_catalog(
        exam_key=clean_exam,
        exam_year=exam_year,
        language=clean_language,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
    )


def start(
    telegram_user: dict,
    *,
    test_instance_id: uuid.UUID,
    client_attempt_id: uuid.UUID,
) -> dict:
    return test_attempts_repo.start(
        test_instance_id,
        _user_id(telegram_user),
        client_attempt_id,
    )


def save_progress(
    telegram_user: dict,
    *,
    attempt_id: uuid.UUID,
    responses: list[dict],
) -> dict:
    clean: list[dict] = []
    seen: set[str] = set()
    for response in responses:
        question_id = str(response["question_id"])
        if question_id in seen:
            raise ValueError("Each question may appear only once per save.")
        seen.add(question_id)
        clean.append(
            {
                "questionId": question_id,
                "selectedIndex": response.get("selected_index"),
                "responseTimeSeconds": response.get("response_time_seconds"),
                "markedForReview": bool(response.get("marked_for_review", False)),
            }
        )
    return test_attempts_repo.save_progress(
        attempt_id,
        _user_id(telegram_user),
        clean,
    )


def advance_section(
    telegram_user: dict,
    *,
    attempt_id: uuid.UUID,
    next_section_instance_id: uuid.UUID,
) -> dict:
    return test_attempts_repo.advance_section(
        attempt_id,
        _user_id(telegram_user),
        next_section_instance_id,
    )


def submit(
    telegram_user: dict,
    *,
    attempt_id: uuid.UUID,
    auto_submit: bool,
) -> dict:
    return test_attempts_repo.submit(
        attempt_id,
        _user_id(telegram_user),
        auto_submit=auto_submit,
    )


def get(telegram_user: dict, *, attempt_id: uuid.UUID) -> dict | None:
    return test_attempts_repo.get(attempt_id, _user_id(telegram_user))


def recent(telegram_user: dict, *, limit: int) -> dict:
    rows = test_attempts_repo.recent(
        _user_id(telegram_user),
        limit=max(1, min(limit, 100)),
    )
    projected = [
        {
            "attemptId": row["id"],
            "testInstanceId": row["test_instance_id"],
            "clientAttemptId": row["client_attempt_id"],
            "status": row["status"],
            "attemptNumber": row["attempt_number"],
            "startedAt": row["started_at"],
            "deadlineAt": row.get("deadline_at"),
            "submittedAt": row.get("submitted_at"),
            "questionCount": row["question_count"],
            "answeredCount": row["answered_count"],
            "correctCount": row["correct_count"],
            "wrongCount": row["wrong_count"],
            "skippedCount": row["skipped_count"],
            "netMarks": float(row["net_marks"]),
        }
        for row in rows
        if row.get("status") in {"in_progress", "submitted", "auto_submitted"}
    ]
    return {
        "count": len(projected),
        "rows": projected,
    }


def _user_id(telegram_user: dict) -> str:
    return str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])
