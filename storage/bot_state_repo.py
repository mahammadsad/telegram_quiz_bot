"""CRUD layer for the `bot_state` key/value table.

Right now this only holds the Telegram getUpdates offset for the
poll-answer sync job, but it's a generic key/value store so any future
small piece of operational state can reuse it instead of inventing a new
table or going back to a committed JSON file.
"""

from __future__ import annotations

from database.client import get_client


def get_value(key: str) -> str | None:
    client = get_client()
    res = client.table("bot_state").select("value").eq("key", key).limit(1).execute()
    rows = res.data or []
    return rows[0]["value"] if rows else None


def set_value(key: str, value: str) -> None:
    client = get_client()
    client.table("bot_state").upsert({"key": key, "value": value}, on_conflict="key").execute()
