"""Supabase persistence for subject quiz lifecycle state."""

from __future__ import annotations

from datetime import datetime, timezone

from config.settings import QUIZ_CLAIM_TIMEOUT_MINUTES
from database.client import get_client


def get(quiz_id: str) -> dict | None:
    result = get_client().table("quiz_runs").select("*").eq("quiz_id", quiz_id).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


def upsert(payload: dict) -> dict:
    values = dict(payload)
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = get_client().table("quiz_runs").upsert(values, on_conflict="quiz_id").execute()
    return result.data[0]


def claim(
    quiz_id: str,
    worker_id: str,
    target_status: str,
    *,
    allow_completed: bool = False,
) -> dict | None:
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
    rows = result.data or []
    return rows[0] if isinstance(rows, list) and rows else None


def update_status(
    quiz_id: str,
    status: str,
    *,
    claimed_by: str | None = None,
    release_claim: bool = False,
    **fields,
) -> dict:
    payload = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
    if release_claim:
        payload.update({"worker_id": None, "claimed_at": None, "claim_expires_at": None})
    query = get_client().table("quiz_runs").update(payload).eq("quiz_id", quiz_id)
    if claimed_by:
        query = query.eq("worker_id", claimed_by)
    result = query.execute()
    rows = result.data or []
    if claimed_by and not rows:
        raise RuntimeError("Quiz run lease was lost before the status update.")
    return rows[0] if rows else {"quiz_id": quiz_id, **payload}


def list_for_date(quiz_date: str) -> list[dict]:
    result = get_client().table("quiz_runs").select("*").eq("quiz_date", quiz_date).execute()
    return result.data or []
