"""Supabase persistence for subject quiz lifecycle state."""

from __future__ import annotations

from datetime import datetime, timezone

from config.settings import QUIZ_CLAIM_TIMEOUT_MINUTES
from database.client import get_client
from storage.contracts import Row, as_rows, first_row


def get(quiz_id: str) -> Row | None:
    result = get_client().table("quiz_runs").select("*").eq("quiz_id", quiz_id).limit(1).execute()
    return first_row(result.data, "quiz_runs.get")


def upsert(payload: Row) -> Row:
    values = dict(payload)
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = get_client().table("quiz_runs").upsert(values, on_conflict="quiz_id").execute()
    row = first_row(result.data, "quiz_runs.upsert")
    if row is None:
        raise RuntimeError("quiz_runs.upsert returned no row")
    return row


def claim(
    quiz_id: str,
    worker_id: str,
    target_status: str,
    *,
    allow_completed: bool = False,
) -> Row | None:
    result = get_client().rpc(
        "claim_quiz_run",
        {
            "p_quiz_id": quiz_id,
            "p_worker_id": worker_id,
            "p_target_status": target_status,
            "p_claim_timeout_minutes": QUIZ_CLAIM_TIMEOUT_MINUTES,
            "p_allow_completed": allow_completed,
        },
    ).execute()
    return first_row(result.data, "quiz_runs.claim")


def update_status(
    quiz_id: str,
    status: str,
    *,
    claimed_by: str | None = None,
    release_claim: bool = False,
    **fields,
) -> Row:
    payload = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
    if release_claim:
        payload.update({"worker_id": None, "claimed_at": None, "claim_expires_at": None})
    query = get_client().table("quiz_runs").update(payload).eq("quiz_id", quiz_id)
    if claimed_by:
        query = query.eq("worker_id", claimed_by)
    result = query.execute()
    rows = as_rows(result.data, "quiz_runs.update_status")
    if claimed_by and not rows:
        raise RuntimeError("Quiz run lease was lost before the status update.")
    return rows[0] if rows else {"quiz_id": quiz_id, **payload}


def list_for_date(quiz_date: str) -> list[Row]:
    result = get_client().table("quiz_runs").select("*").eq("quiz_date", quiz_date).execute()
    return as_rows(result.data, "quiz_runs.list_for_date")
