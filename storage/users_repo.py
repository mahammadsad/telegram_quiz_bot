"""CRUD layer for the `users` table."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from database.client import get_client
from models.user import User

LOG = logging.getLogger("storage.users")


def upsert_user(user: User) -> dict:
    """Insert a new user or refresh username/name/last_active for an
    existing one, keyed on telegram_id (unique constraint in the schema)."""
    client = get_client()
    payload = {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "last_active": datetime.now(timezone.utc).isoformat(),
    }
    res = (
        client.table("users")
        .upsert(payload, on_conflict="telegram_id")
        .execute()
    )
    return res.data[0]


def get_by_telegram_id(telegram_id: int) -> dict | None:
    client = get_client()
    res = (
        client.table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None
