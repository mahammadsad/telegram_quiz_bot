"""CRUD layer for the `user_attempts` table."""

from __future__ import annotations

import logging

from database.client import get_client
from models.attempt import Attempt
from storage.contracts import Row, as_rows, first_row

LOG = logging.getLogger("storage.attempts")


def insert_attempt(attempt: Attempt) -> Row | None:
    """Record one raw answer event.

    Uses ignore_duplicates on (user_id, poll_id) because Telegram quiz
    polls lock a user's vote after their first answer, but the poll-answer
    sync job may see the same update more than once (e.g. if a run is
    retried) — this makes the insert idempotent instead of raising a
    unique-constraint error.

    Returns None if the attempt already existed (ignored), otherwise the
    inserted row.
    """
    client = get_client()
    res = (
        client.table("user_attempts")
        .upsert(attempt.to_insert_dict(), on_conflict="user_id,poll_id", ignore_duplicates=True)
        .execute()
    )
    if res.data:
        LOG.info("Recorded attempt: user=%s question=%s correct=%s",
                  attempt.user_id, attempt.question_id, attempt.is_correct)
        return first_row(res.data, "user_attempts.insert")
    LOG.info("Attempt already recorded for user=%s poll=%s, skipped.", attempt.user_id, attempt.poll_id)
    return None


def get_for_user_by_poll_ids(user_id: str, poll_ids: list[str]) -> list[Row]:
    if not poll_ids:
        return []
    client = get_client()
    res = (
        client.table("user_attempts")
        .select("*")
        .eq("user_id", user_id)
        .in_("poll_id", poll_ids)
        .execute()
    )
    return as_rows(res.data, "user attempts by poll")
