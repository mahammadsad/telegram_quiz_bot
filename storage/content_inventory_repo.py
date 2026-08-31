"""Server-only persistence for Phase C inventory and replenishment jobs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from database.client import get_client
from storage.contracts import Row, as_row, as_rows


def list_verified_candidates(
    subject_key: str,
    *,
    now: datetime,
    limit: int = 300,
) -> list[Row]:
    result = get_client().rpc(
        "get_verified_question_inventory",
        {"p_subject_key": subject_key, "p_now": now.isoformat(), "p_limit": limit},
    ).execute()
    return as_rows(result.data, "verified question inventory")


def list_recent_usage(subject_key: str, *, since: datetime) -> list[Row]:
    result = get_client().rpc(
        "get_recent_content_usage",
        {"p_subject_key": subject_key, "p_since": since.isoformat()},
    ).execute()
    return as_rows(result.data, "recent content usage")


def list_recent_replenishment_events(
    *,
    since: datetime,
    limit: int = 1000,
) -> list[Row]:
    """Return bounded answer-free replenishment diagnostics for operators."""
    bounded_limit = max(1, min(limit, 5000))
    result = (
        get_client()
        .table("content_replenishment_job_events")
        .select(
            "event_type,accepted_count,rejected_count,rejection_codes,error_code,created_at"
        )
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(bounded_limit)
        .execute()
    )
    return as_rows(result.data, "recent content replenishment events")


def existing_candidate_identities(
    *,
    variant_fingerprints: list[str],
    stem_hashes: list[str],
    content_hashes: list[str],
) -> tuple[set[str], set[str], set[str]]:
    """Return server-only identities that already exist in durable questions."""
    client = get_client()

    def existing(field: str, values: list[str]) -> set[str]:
        unique = sorted({value for value in values if value})
        if not unique:
            return set()
        result = (
            client.table("questions")
            .select(field)
            .in_(field, unique)
            .execute()
        )
        return {
            str(row[field])
            for row in as_rows(result.data, f"existing question {field}")
            if row.get(field)
        }

    return (
        existing("variant_fingerprint", variant_fingerprints),
        existing("stem_hash", stem_hashes),
        existing("content_hash", content_hashes),
    )


def ensure_replenishment_job(
    *,
    logical_date: date,
    subject_key: str,
    micro_topic_id: str | None,
    due_at: datetime,
    target_candidate_count: int = 15,
    generation_batch_size: int = 5,
) -> Row:
    result = get_client().rpc(
        "ensure_content_replenishment_job",
        {
            "p_logical_date": logical_date.isoformat(),
            "p_subject_key": subject_key,
            "p_micro_topic_id": micro_topic_id,
            "p_due_at": due_at.isoformat(),
            "p_target_candidate_count": target_candidate_count,
            "p_generation_batch_size": generation_batch_size,
        },
    ).execute()
    return as_row(result.data, "ensure content replenishment job")


def claim_replenishment_jobs(
    *, worker_id: str, now: datetime, lease_minutes: int = 20, limit: int = 5
) -> list[Row]:
    result = get_client().rpc(
        "claim_content_replenishment_jobs",
        {
            "p_worker_id": worker_id,
            "p_now": now.isoformat(),
            "p_lease_minutes": lease_minutes,
            "p_limit": limit,
        },
    ).execute()
    return as_rows(result.data, "claim content replenishment jobs")


def complete_replenishment_batch(
    *,
    job_id: str,
    worker_id: str,
    accepted_count: int,
    rejected_count: int,
    rejection_codes: list[str],
    error_code: str | None = None,
    retry_at: datetime | None = None,
) -> Row:
    payload: dict[str, Any] = {
        "p_job_id": job_id,
        "p_worker_id": worker_id,
        "p_accepted_count": accepted_count,
        "p_rejected_count": rejected_count,
        "p_rejection_codes": rejection_codes,
        "p_error_code": error_code,
        "p_retry_at": retry_at.isoformat() if retry_at else None,
    }
    result = get_client().rpc("complete_content_replenishment_batch", payload).execute()
    return as_row(result.data, "complete content replenishment batch")


def save_verified_candidates(
    candidates: list[dict[str, Any]],
    generation_context: dict[str, Any],
) -> Row:
    result = get_client().rpc(
        "save_verified_content_candidates",
        {
            "p_candidates": candidates,
            "p_generation_context": generation_context,
        },
    ).execute()
    return as_row(result.data, "save verified content candidates")


def ensure_due_replenishment_jobs(*, now: datetime) -> list[Row]:
    result = get_client().rpc(
        "ensure_due_content_replenishment_jobs",
        {"p_now": now.isoformat()},
    ).execute()
    return as_rows(result.data, "ensure due content replenishment jobs")


def get_replenishment_bundle(
    job_id: str,
    *,
    now: datetime,
    limit: int = 8,
) -> list[Row]:
    result = get_client().rpc(
        "get_content_replenishment_bundle",
        {"p_job_id": job_id, "p_now": now.isoformat(), "p_limit": limit},
    ).execute()
    return as_rows(result.data, "content replenishment bundle")
