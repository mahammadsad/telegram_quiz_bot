"""CRUD layer for the `polls` table."""

from __future__ import annotations

import logging

from database.client import get_client
from models.poll import Poll
from storage.contracts import Row, as_rows, first_row

LOG = logging.getLogger("storage.polls")


def insert_poll(poll: Poll) -> Row:
    client = get_client()
    res = client.table("polls").insert(poll.to_insert_dict()).execute()
    row = first_row(res.data, "polls.insert")
    if row is None:
        raise RuntimeError("polls.insert returned no row")
    LOG.info("Recorded poll %s (telegram_poll_id=%s)", row["id"], row["telegram_poll_id"])
    return row


def upsert_poll(poll: Poll) -> Row:
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
    row = first_row(res.data, "polls.upsert")
    if row is None:
        raise RuntimeError("polls.upsert returned no row")
    LOG.info("Upserted poll delivery %s (telegram_poll_id=%s)", row["id"], row["telegram_poll_id"])
    return row


def get_by_telegram_poll_id(telegram_poll_id: str) -> Row | None:
    client = get_client()
    res = (
        client.table("polls")
        .select("*")
        .eq("telegram_poll_id", telegram_poll_id)
        .limit(1)
        .execute()
    )
    return first_row(res.data, "polls.by_telegram_id")


def get_by_run_slot(run_slot: str, bot_type: str) -> list[Row]:
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
    return as_rows(res.data, "polls.by_run_slot")


def delete_by_run_slot(run_slot: str, bot_type: str) -> None:
    get_client().table("polls").delete().eq("bot_type", bot_type).eq("run_slot", run_slot).execute()
