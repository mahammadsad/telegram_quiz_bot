"""Service-role persistence for versioned exam and shared-test projections."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError


def exam_catalog(
    *,
    as_of: str,
    exam_key: str | None,
    limit: int,
    offset: int,
) -> dict:
    return _rpc(
        "get_exam_configuration_catalog",
        {
            "p_as_of": as_of,
            "p_exam_key": exam_key,
            "p_limit": limit,
            "p_offset": offset,
        },
    )


def test_definition_catalog(
    *,
    as_of: str,
    test_type: str | None,
    limit: int,
    offset: int,
) -> dict:
    return _rpc(
        "get_test_definition_catalog",
        {
            "p_as_of": as_of,
            "p_test_type": test_type,
            "p_limit": limit,
            "p_offset": offset,
        },
    )


def public_test_instance(test_instance_id: str) -> dict | None:
    result = get_client().rpc(
        "get_public_test_instance",
        {"p_test_instance_id": test_instance_id},
    ).execute()
    if result.data is None:
        return None
    if not isinstance(result.data, dict) or "sections" not in result.data:
        raise DatabaseIntegrityError(
            "get_public_test_instance returned an invalid response."
        )
    return result.data


def learning_test_catalog(
    *,
    exam_key: str | None,
    test_type: str | None,
    subject_key: str | None,
    limit: int,
    offset: int,
) -> dict:
    return _rpc(
        "get_learning_test_catalog",
        {
            "p_exam_key": exam_key,
            "p_test_type": test_type,
            "p_subject_key": subject_key,
            "p_limit": limit,
            "p_offset": offset,
        },
    )


def _rpc(name: str, payload: dict) -> dict:
    result = get_client().rpc(name, payload).execute()
    if not isinstance(result.data, dict) or "rows" not in result.data:
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    return result.data
