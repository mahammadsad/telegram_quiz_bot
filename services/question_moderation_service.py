"""Admin-only question quarantine, correction, and review workflows."""

from __future__ import annotations

import hashlib

from services.resource_quality_service import is_admin
from storage import question_moderation_repo

CASE_STATUSES = {
    "open",
    "under_review",
    "quarantined",
    "resolved",
    "dismissed",
    "superseded",
    "reinstated",
}
REVIEW_DECISIONS = {
    "start_review",
    "resolve_confirmed",
    "dismiss",
    "supersede",
    "reinstate",
}
AUTHORITATIVE_TRIGGERS = {
    "deterministic_contradiction",
    "authoritative_correction",
}


def admin_review_queue(
    telegram_user: dict,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> dict:
    _require_admin(telegram_user)
    clean_status = status.strip() if status else None
    if clean_status and clean_status not in CASE_STATUSES:
        raise ValueError("Invalid moderation case status.")
    return question_moderation_repo.review_queue(
        status=clean_status,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
    )


def review_case(
    telegram_user: dict,
    *,
    case_id: str,
    decision: str,
    resolution: str,
    superseding_question_id: str | None,
) -> dict:
    _require_admin(telegram_user)
    if decision not in REVIEW_DECISIONS:
        raise ValueError("Invalid question review decision.")
    clean_resolution = resolution.strip()
    if not clean_resolution:
        raise ValueError("A review resolution is required.")
    if len(clean_resolution) > 2000:
        raise ValueError("Review resolution must be 2000 characters or fewer.")
    if decision == "supersede" and not superseding_question_id:
        raise ValueError("A superseding question is required.")
    if decision != "supersede" and superseding_question_id:
        raise ValueError("A superseding question is only valid for supersede.")
    return question_moderation_repo.review_case(
        case_id,
        decision=decision,
        actor=_actor(telegram_user),
        resolution=clean_resolution,
        superseding_question_id=superseding_question_id,
    )


def authoritative_quarantine(
    telegram_user: dict,
    *,
    question_id: str,
    trigger: str,
    reason: str,
    superseding_question_id: str | None,
) -> dict:
    _require_admin(telegram_user)
    if trigger not in AUTHORITATIVE_TRIGGERS:
        raise ValueError("Invalid authoritative quarantine trigger.")
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("A quarantine reason is required.")
    if len(clean_reason) > 2000:
        raise ValueError("Quarantine reason must be 2000 characters or fewer.")
    if trigger == "authoritative_correction" and not superseding_question_id:
        raise ValueError("An authoritative correction requires a superseding question.")
    if trigger == "deterministic_contradiction" and superseding_question_id:
        raise ValueError("A deterministic contradiction does not accept a replacement.")
    return question_moderation_repo.quarantine_question(
        question_id,
        trigger=trigger,
        actor=_actor(telegram_user),
        reason=clean_reason,
        superseding_question_id=superseding_question_id,
    )


def _require_admin(telegram_user: dict) -> None:
    if not is_admin(telegram_user):
        raise PermissionError("Administrator access required.")


def _actor(telegram_user: dict) -> str:
    return "telegram-admin:" + hashlib.sha256(str(telegram_user["id"]).encode("utf-8")).hexdigest()[:12]
