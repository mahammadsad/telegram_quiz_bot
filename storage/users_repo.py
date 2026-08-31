"""CRUD layer for the `users` table."""

from __future__ import annotations

from database.client import get_client
from database.observability import database_timing
from errors import DatabaseIntegrityError
from models.user import User
from storage.contracts import Row, first_row


def upsert_user(user: User) -> Row:
    """Resolve identity and touch activity at most once every 15 minutes."""
    payload = {
        "p_telegram_id": user.telegram_id,
        "p_username": user.username,
        "p_first_name": user.first_name,
        "p_last_name": user.last_name,
        "p_photo_url": user.photo_url,
        "p_touch_interval_seconds": 900,
    }
    with database_timing("users.resolve"):
        result = get_client().rpc("resolve_telegram_user_v2", payload).execute()
    if not isinstance(result.data, dict) or not result.data.get("id"):
        raise DatabaseIntegrityError("users.resolve returned an invalid response.")
    return result.data


def get_by_telegram_id(telegram_id: int) -> Row | None:
    client = get_client()
    with database_timing("users.lookup"):
        res = (
            client.table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
    return first_row(res.data, "users.select")
