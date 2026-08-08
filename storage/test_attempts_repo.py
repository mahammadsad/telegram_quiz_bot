"""Service-role persistence for previous-year catalogues and timed tests."""

from __future__ import annotations

import uuid
from typing import Any

from database.client import get_client
from errors import DatabaseIntegrityError


def previous_year_catalog(
    *,
    exam_key: str | None,
    exam_year: int | None,
    language: str | None,
    limit: int,
    offset: int,
) -> dict:
    return _rpc(
        "get_previous_year_question_catalog",
        {
            "p_exam_key": exam_key,
            "p_exam_year": exam_year,
            "p_language": language,
            "p_limit": limit,
            "p_offset": offset,
        },
        require_rows=True,
    )


def start(test_instance_id: uuid.UUID, user_id: str, client_attempt_id: uuid.UUID) -> dict:
    return _rpc(
        "start_test_attempt_atomic",
        {
            "p_test_instance_id": str(test_instance_id),
            "p_user_id": user_id,
            "p_client_attempt_id": str(client_attempt_id),
        },
    )


def save_progress(attempt_id: uuid.UUID, user_id: str, responses: list[dict]) -> dict:
    return _rpc(
        "save_test_attempt_progress_atomic",
        {
            "p_attempt_id": str(attempt_id),
            "p_user_id": user_id,
            "p_responses": responses,
        },
    )


def advance_section(
    attempt_id: uuid.UUID,
    user_id: str,
    next_section_instance_id: uuid.UUID,
) -> dict:
    return _rpc(
        "advance_test_attempt_section_atomic",
        {
            "p_attempt_id": str(attempt_id),
            "p_user_id": user_id,
            "p_next_section_instance_id": str(next_section_instance_id),
        },
    )


def submit(attempt_id: uuid.UUID, user_id: str, *, auto_submit: bool) -> dict:
    return _rpc(
        "submit_test_attempt_atomic",
        {
            "p_attempt_id": str(attempt_id),
            "p_user_id": user_id,
            "p_auto_submit": auto_submit,
        },
    )


def get(attempt_id: uuid.UUID, user_id: str) -> dict | None:
    result = get_client().rpc(
        "get_test_attempt_for_user",
        {"p_attempt_id": str(attempt_id), "p_user_id": user_id},
    ).execute()
    if result.data is None:
        return None
    if not isinstance(result.data, dict) or "attemptId" not in result.data:
        raise DatabaseIntegrityError("get_test_attempt_for_user returned an invalid response.")
    return result.data


def _rpc(name: str, payload: dict[str, Any], *, require_rows: bool = False) -> dict:
    result = get_client().rpc(name, payload).execute()
    if not isinstance(result.data, dict):
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    required_key = "rows" if require_rows else "attemptId"
    if required_key not in result.data:
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    return result.data
