"""CRUD layer for the `polls` table."""

from __future__ import annotations

import logging
from typing import Optional

from database.client import get_client
from models.poll import Poll

LOG = logging.getLogger("storage.polls")


def insert_poll(poll: Poll) -> dict:
    client = get_client()
    res = client.table("polls").insert(poll.to_insert_dict()).execute()
    row = res.data[0]
    LOG.info("Recorded poll %s (telegram_poll_id=%s)", row["id"], row["telegram_poll_id"])
    return row


def upsert_poll(poll: Poll) -> dict:
    """Insert or refresh a delivery record keyed by telegram_poll_id.

    repo_2's Mini App quizzes are not Telegram native polls, but they still
    use this shared table as the per-question delivery/session record. That
    lets user_attempts keep repo_1's same unique (user_id, poll_id) behavior.
    """
    client = get_client()
    res = (
        client.table("polls")
        .upsert(poll.to_insert_dict(), on_conflict="telegram_poll_id")
        .execute()
    )
    row = res.data[0]
    LOG.info("Upserted poll delivery %s (telegram_poll_id=%s)", row["id"], row["telegram_poll_id"])
    return row


def get_by_telegram_poll_id(telegram_poll_id: str) -> Optional[dict]:
    client = get_client()
    res = (
        client.table("polls")
        .select("*")
        .eq("telegram_poll_id", telegram_poll_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def get_by_run_slot(run_slot: str, bot_type: str) -> list[dict]:
    """Return all delivery rows for a quiz/session, ordered by question index."""
    client = get_client()
    res = (
        client.table("polls")
        .select("*")
        .eq("bot_type", bot_type)
        .eq("run_slot", run_slot)
        .order("telegram_message_id")
        .execute()
    )
    return res.data or []


def delete_by_run_slot(run_slot: str, bot_type: str) -> None:
    get_client().table("polls").delete().eq("bot_type", bot_type).eq("run_slot", run_slot).execute()
