"""Durable quiz job persistence and lifecycle RPCs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.client import get_client
from storage.contracts import Row, as_row, as_rows


def ensure_daily(
    specs: list[dict[str, str]],
    *,
    configuration_hash: str,
    code_sha: str,
    source_bundle_hash: str | None = None,
) -> list[Row]:
    result = get_client().rpc(
        "ensure_daily_quiz_jobs",
        {
            "p_jobs": specs,
            "p_configuration_hash": configuration_hash,
            "p_code_sha": code_sha,
            "p_source_bundle_hash": source_bundle_hash,
        },
    ).execute()
    return as_rows(result.data, "ensure_daily_quiz_jobs")


def claim_due(
    *,
    worker_id: str,
    now: datetime,
    lease_minutes: int,
    limit: int = 13,
) -> list[Row]:
    result = get_client().rpc(
        "claim_due_quiz_jobs",
        {
            "p_worker_id": worker_id,
            "p_now": now.isoformat(),
            "p_lease_minutes": lease_minutes,
            "p_limit": limit,
        },
    ).execute()
    return as_rows(result.data, "claim_due_quiz_jobs")


def transition(
    *,
    job_id: str,
    worker_id: str,
    target_status: str,
    event_type: str,
    detail: dict[str, Any] | None = None,
    pack_checksum: str | None = None,
) -> Row:
    result = get_client().rpc(
        "transition_quiz_job",
        {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_target_status": target_status,
            "p_event_type": event_type,
            "p_detail": detail or {},
            "p_pack_checksum": pack_checksum,
        },
    ).execute()
    return as_row(result.data, "transition_quiz_job")


def fail(
    *,
    job_id: str,
    worker_id: str,
    retryable: bool,
    category: str,
    code: str,
    reason: str,
    max_retries: int,
    base_delay_seconds: int,
    max_delay_seconds: int,
) -> Row:
    result = get_client().rpc(
        "fail_quiz_job",
        {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_retryable": retryable,
            "p_category": category,
            "p_code": code,
            "p_reason": reason,
            "p_max_retries": max_retries,
            "p_base_delay_seconds": base_delay_seconds,
            "p_max_delay_seconds": max_delay_seconds,
        },
    ).execute()
    return as_row(result.data, "fail_quiz_job")


def sync_posted_run(*, quiz_id: str, worker_id: str) -> Row:
    result = get_client().rpc(
        "sync_quiz_job_from_posted_run",
        {"p_quiz_id": quiz_id, "p_worker_id": worker_id},
    ).execute()
    return as_row(result.data, "sync_quiz_job_from_posted_run")


def mark_posting_unknown(
    *,
    job_id: str,
    worker_id: str,
    category: str,
    code: str,
    reason: str,
) -> Row:
    result = get_client().rpc(
        "mark_quiz_job_posting_unknown",
        {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_category": category,
            "p_code": code,
            "p_reason": reason,
        },
    ).execute()
    return as_row(result.data, "mark_quiz_job_posting_unknown")


def list_for_date(logical_date: str) -> list[Row]:
    result = (
        get_client()
        .table("quiz_jobs")
        .select("*")
        .eq("logical_date", logical_date)
        .order("due_at")
        .execute()
    )
    return as_rows(result.data, "quiz_jobs.list_for_date")


def list_delivery_slo_window(start_date: str, end_date: str) -> list[Row]:
    result = (
        get_client()
        .table("quiz_jobs")
        .select("logical_date,subject_key,due_at,status,posted_at")
        .gte("logical_date", start_date)
        .lte("logical_date", end_date)
        .order("logical_date")
        .order("subject_key")
        .execute()
    )
    return as_rows(result.data, "quiz_jobs.delivery_slo_window")


def reconcile_unknown(
    *,
    job_id: str,
    action: str,
    actor: str,
    reason: str,
    telegram_message_id: int | None = None,
) -> Row:
    result = get_client().rpc(
        "reconcile_quiz_job_unknown",
        {
            "p_job_id": job_id,
            "p_action": action,
            "p_actor": actor,
            "p_reason": reason,
            "p_telegram_message_id": telegram_message_id,
        },
    ).execute()
    return as_row(result.data, "reconcile_quiz_job_unknown")
