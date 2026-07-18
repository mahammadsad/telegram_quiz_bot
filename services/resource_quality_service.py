"""Authenticated resource feedback, operator review, and safe health views."""

from __future__ import annotations

import hashlib
import re
import time

from config.settings import TELEGRAM_ADMIN_USER_IDS
from models.user import User
from storage import resource_quality_repo, users_repo

FEEDBACK_TYPES = {
    "video_unavailable",
    "article_unavailable",
    "not_useful",
    "wrong_language",
    "topic_mismatch",
    "low_quality",
}
REVIEW_DECISIONS = {"approve", "reject", "archive"}
_PUBLIC_CACHE: tuple[float, dict] | None = None


def submit_feedback(
    telegram_user: dict,
    *,
    resource_id: str,
    feedback_type: str,
    rating: int | None,
    details: str | None,
) -> dict:
    if feedback_type not in FEEDBACK_TYPES:
        raise ValueError("Invalid resource feedback type.")
    if rating is not None and (isinstance(rating, bool) or rating not in range(1, 6)):
        raise ValueError("Rating must be between 1 and 5.")
    clean_details = details.strip() if details else None
    if clean_details and len(clean_details) > 500:
        raise ValueError("Feedback details are too long.")
    return resource_quality_repo.submit_feedback(
        _user_id(telegram_user),
        resource_id=resource_id,
        feedback_type=feedback_type,
        rating=rating,
        details=clean_details,
    )


def public_operational_status() -> dict:
    global _PUBLIC_CACHE
    now = time.monotonic()
    if _PUBLIC_CACHE and now - _PUBLIC_CACHE[0] < 30:
        return _PUBLIC_CACHE[1]
    raw = resource_quality_repo.operational_status()
    raw_resources = raw.get("resources")
    resources = raw_resources if isinstance(raw_resources, dict) else {}
    result = {
        "database_connectivity": bool(raw.get("databaseConnectivity")),
        "required_schema_ready": bool(raw.get("schemaReady")),
        "latest_successful_generation": raw.get("latestSuccessfulGeneration"),
        "latest_successful_posting": raw.get("latestSuccessfulPosting"),
        "failed_runs_today": int(raw.get("failedRunsToday") or 0),
        "static_resource_health": {
            "active_verified": int(resources.get("activeVerified") or 0),
            "due_checks": int(resources.get("dueChecks") or 0),
            "hard_failures_24h": int(resources.get("hardFailures24h") or 0),
        },
    }
    _PUBLIC_CACHE = (now, result)
    return result


def admin_operational_status(telegram_user: dict) -> dict:
    _require_admin(telegram_user)
    return resource_quality_repo.operational_status()


def admin_review_queue(telegram_user: dict, *, limit: int, offset: int) -> dict:
    _require_admin(telegram_user)
    return resource_quality_repo.review_queue(
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
    )


def review_candidate(
    telegram_user: dict,
    *,
    resource_id: str,
    decision: str,
) -> dict:
    _require_admin(telegram_user)
    if decision not in REVIEW_DECISIONS:
        raise ValueError("Invalid resource review decision.")
    actor = "telegram-admin:" + hashlib.sha256(
        str(telegram_user["id"]).encode("utf-8")
    ).hexdigest()[:12]
    return resource_quality_repo.review_candidate(
        resource_id,
        decision=decision,
        actor=actor,
    )


def is_admin(telegram_user: dict) -> bool:
    try:
        user_id = int(telegram_user["id"])
    except (KeyError, TypeError, ValueError):
        return False
    return user_id in {
        int(value)
        for value in re.findall(r"-?\d+", TELEGRAM_ADMIN_USER_IDS)
    }


def _require_admin(telegram_user: dict) -> None:
    if not is_admin(telegram_user):
        raise PermissionError("Administrator access required.")


def _user_id(telegram_user: dict) -> str:
    row = users_repo.upsert_user(User.from_telegram(telegram_user))
    user_id = str(row.get("id") or "")
    if not user_id:
        raise RuntimeError("User profile could not be resolved.")
    return user_id
