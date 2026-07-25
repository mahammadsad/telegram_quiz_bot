"""Service-role resource quality, discovery, review, and operations RPCs."""

from __future__ import annotations

from typing import Any

from database.client import get_client
from errors import DatabaseIntegrityError
from storage.contracts import Row, as_int, as_row, as_rows, raise_safe_rate_limit


def submit_feedback(
    user_id: str,
    *,
    resource_id: str,
    feedback_type: str,
    rating: int | None,
    details: str | None,
) -> Row:
    return _rpc(
        "submit_resource_feedback",
        {
            "p_user_id": user_id,
            "p_resource_id": resource_id,
            "p_feedback_type": feedback_type,
            "p_rating": rating,
            "p_details": details,
        },
    )


def operational_status() -> Row:
    return _rpc("get_operational_status", {})


def review_queue(*, limit: int, offset: int) -> Row:
    return _rpc(
        "get_resource_review_queue",
        {"p_limit": limit, "p_offset": offset},
    )


def review_candidate(resource_id: str, *, decision: str, actor: str) -> Row:
    return _rpc(
        "review_resource_candidate",
        {
            "p_resource_id": resource_id,
            "p_decision": decision,
            "p_actor": actor,
        },
    )


def link_check_batch(*, limit: int) -> list[Row]:
    result = get_client().rpc(
        "get_resource_link_check_batch",
        {"p_limit": max(1, min(limit, 200))},
    ).execute()
    return as_rows(result.data, "resource link-check batch")


def record_link_check(resource_id: str, payload: dict[str, Any]) -> Row:
    return _rpc(
        "record_resource_link_check",
        {
            "p_resource_id": resource_id,
            "p_outcome": payload["outcome"],
            "p_status_code": payload.get("status_code"),
            "p_error_category": payload["error_category"],
            "p_response_ms": payload.get("response_ms"),
        },
    )


def queue_missing_resources(*, limit: int = 200) -> int:
    result = get_client().rpc(
        "queue_missing_resource_discovery",
        {"p_limit": max(1, min(limit, 500))},
    ).execute()
    return 0 if result.data is None else as_int(result.data, "resource discovery queue")


def discovery_batch(*, limit: int = 5) -> list[Row]:
    result = get_client().rpc(
        "get_resource_discovery_batch",
        {"p_limit": max(1, min(limit, 20))},
    ).execute()
    return as_rows(result.data, "resource discovery batch")


def save_youtube_candidate(queue_id: str, payload: dict[str, Any]) -> Row:
    return _rpc(
        "save_youtube_resource_candidate",
        {"p_queue_id": queue_id, **payload},
    )


def complete_discovery(
    queue_id: str,
    *,
    outcome: str,
    error_category: str | None = None,
) -> Row:
    return _rpc(
        "complete_resource_discovery",
        {
            "p_queue_id": queue_id,
            "p_outcome": outcome,
            "p_error_category": error_category,
        },
    )


def channel_policies() -> list[Row]:
    result = get_client().table("resource_channel_policies").select(
        "channel_id,policy,default_language"
    ).execute()
    return as_rows(result.data, "resource channel policies")


def _rpc(name: str, payload: dict[str, Any]) -> Row:
    try:
        result = get_client().rpc(name, payload).execute()
    except Exception as exc:
        raise_safe_rate_limit(exc)
        raise
    if not isinstance(result.data, dict):
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    return as_row(result.data, name)
