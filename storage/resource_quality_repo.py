"""Service-role resource quality, discovery, review, and operations RPCs."""

from __future__ import annotations

from typing import Any

from database.client import get_client
from errors import DatabaseIntegrityError


def submit_feedback(
    user_id: str,
    *,
    resource_id: str,
    feedback_type: str,
    rating: int | None,
    details: str | None,
) -> dict:
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


def operational_status() -> dict:
    return _rpc("get_operational_status", {})


def review_queue(*, limit: int, offset: int) -> dict:
    return _rpc(
        "get_resource_review_queue",
        {"p_limit": limit, "p_offset": offset},
    )


def review_candidate(resource_id: str, *, decision: str, actor: str) -> dict:
    return _rpc(
        "review_resource_candidate",
        {
            "p_resource_id": resource_id,
            "p_decision": decision,
            "p_actor": actor,
        },
    )


def link_check_batch(*, limit: int) -> list[dict]:
    result = get_client().rpc(
        "get_resource_link_check_batch",
        {"p_limit": max(1, min(limit, 200))},
    ).execute()
    return result.data or []


def record_link_check(resource_id: str, payload: dict[str, Any]) -> dict:
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
    return int(result.data or 0)


def discovery_batch(*, limit: int = 5) -> list[dict]:
    result = get_client().rpc(
        "get_resource_discovery_batch",
        {"p_limit": max(1, min(limit, 20))},
    ).execute()
    return result.data or []


def save_youtube_candidate(queue_id: str, payload: dict[str, Any]) -> dict:
    return _rpc(
        "save_youtube_resource_candidate",
        {"p_queue_id": queue_id, **payload},
    )


def complete_discovery(
    queue_id: str,
    *,
    outcome: str,
    error_category: str | None = None,
) -> dict:
    return _rpc(
        "complete_resource_discovery",
        {
            "p_queue_id": queue_id,
            "p_outcome": outcome,
            "p_error_category": error_category,
        },
    )


def channel_policies() -> list[dict]:
    result = get_client().table("resource_channel_policies").select(
        "channel_id,policy,default_language"
    ).execute()
    return result.data or []


def _rpc(name: str, payload: dict[str, Any]) -> dict:
    result = get_client().rpc(name, payload).execute()
    if not isinstance(result.data, dict):
        raise DatabaseIntegrityError(f"{name} returned an invalid response.")
    return result.data
