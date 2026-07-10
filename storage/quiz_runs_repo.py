"""Supabase persistence for subject quiz lifecycle state."""

from __future__ import annotations

from datetime import datetime, timezone

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


def update_status(quiz_id: str, status: str, **fields) -> dict:
    payload = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
    result = get_client().table("quiz_runs").update(payload).eq("quiz_id", quiz_id).execute()
    rows = result.data or []
    return rows[0] if rows else {"quiz_id": quiz_id, **payload}


def list_for_date(quiz_date: str) -> list[dict]:
    result = get_client().table("quiz_runs").select("*").eq("quiz_date", quiz_date).execute()
    return result.data or []
