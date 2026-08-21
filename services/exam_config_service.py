"""Public, answer-free projections of versioned exams and shared tests."""

from __future__ import annotations

import uuid
from datetime import date

from storage import exam_config_repo

TEST_TYPES = {
    "daily_quick",
    "chapter",
    "subject",
    "mixed",
    "previous_year",
    "previous_year_style",
    "sectional_mock",
    "full_mock",
}


def exam_catalog(
    *,
    as_of: date | None,
    exam_key: str | None,
    limit: int,
    offset: int,
) -> dict:
    clean_exam = exam_key.strip().upper() if exam_key else None
    if clean_exam and (
        len(clean_exam) > 50
        or any(character.isspace() for character in clean_exam)
    ):
        raise ValueError("Invalid exam key.")
    return exam_config_repo.exam_catalog(
        as_of=(as_of or date.today()).isoformat(),
        exam_key=clean_exam,
        limit=_page_limit(limit),
        offset=max(0, offset),
    )


def test_definition_catalog(
    *,
    as_of: date | None,
    test_type: str | None,
    limit: int,
    offset: int,
) -> dict:
    clean_type = test_type.strip() if test_type else None
    if clean_type and clean_type not in TEST_TYPES:
        raise ValueError("Unknown test type.")
    return exam_config_repo.test_definition_catalog(
        as_of=(as_of or date.today()).isoformat(),
        test_type=clean_type,
        limit=_page_limit(limit),
        offset=max(0, offset),
    )


def public_test_instance(test_instance_id: uuid.UUID) -> dict | None:
    return exam_config_repo.public_test_instance(str(test_instance_id))


def learning_test_catalog(
    *,
    exam_key: str | None,
    test_type: str | None,
    subject_key: str | None,
    limit: int,
    offset: int,
) -> dict:
    clean_exam = exam_key.strip().upper() if exam_key else None
    clean_type = test_type.strip() if test_type else None
    clean_subject = subject_key.strip().lower() if subject_key else None
    if clean_exam and (len(clean_exam) > 50 or any(char.isspace() for char in clean_exam)):
        raise ValueError("Invalid exam key.")
    if clean_type and clean_type not in TEST_TYPES:
        raise ValueError("Unknown test type.")
    if clean_subject and (
        len(clean_subject) > 50
        or not all(char.isalnum() or char == "-" for char in clean_subject)
    ):
        raise ValueError("Invalid subject key.")
    return exam_config_repo.learning_test_catalog(
        exam_key=clean_exam,
        test_type=clean_type,
        subject_key=clean_subject,
        limit=_page_limit(limit),
        offset=max(0, offset),
    )


def _page_limit(value: int) -> int:
    return max(1, min(value, 100))
