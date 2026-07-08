"""CRUD + query layer for the `questions` table.

This is the only module allowed to run Supabase queries against
`questions`. Everything else (scheduler, generator, services) goes
through these functions, which keeps the query surface auditable in one
place — useful once the Mock Test Bot and Website start reading the same
table from separate repos.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from config.settings import BOT_TYPE, SIMILARITY_THRESHOLD
from database.client import get_client
from models.question import Question

LOG = logging.getLogger("storage.questions")


def get_by_id(question_id: str) -> Optional[dict]:
    client = get_client()
    res = client.table("questions").select("*").eq("id", question_id).limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def get_by_hash(question_hash: str, bot_type: str = BOT_TYPE) -> Optional[dict]:
    """Layer 1 of duplicate detection: exact-hash lookup."""
    client = get_client()
    res = (
        client.table("questions")
        .select("*")
        .eq("question_hash", question_hash)
        .eq("bot_type", bot_type)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def get_by_hash_any_bot(question_hash: str) -> Optional[dict]:
    """Exact-hash lookup across the shared question bank.

    The schema's question_hash constraint is global, not per bot_type, so a
    mock-test pack must reuse a matching daily_mcq row instead of attempting
    an insert that Postgres would reject.
    """
    client = get_client()
    res = (
        client.table("questions")
        .select("*")
        .eq("question_hash", question_hash)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def find_similar(normalized_text: str, bot_type: str = BOT_TYPE,
                  threshold: float = SIMILARITY_THRESHOLD, limit: int = 5) -> list[dict]:
    """Layer 3 of duplicate detection: fuzzy match via the Postgres
    find_similar_questions() function (pg_trgm, see database/schema.sql).
    Returns rows already sorted by similarity descending."""
    client = get_client()
    res = client.rpc(
        "find_similar_questions",
        {
            "query_normalized": normalized_text,
            "query_bot_type": bot_type,
            "sim_threshold": threshold,
            "match_count": limit,
        },
    ).execute()
    return [r for r in (res.data or []) if r.get("similarity", 0) >= threshold]


def insert_question(question: Question) -> dict:
    client = get_client()
    res = client.table("questions").insert(question.to_insert_dict()).execute()
    row = res.data[0]
    LOG.info("Inserted new question %s [%s/%s]", row["id"], row["subject"], row["topic"])
    return row


def get_eligible_pool(subject: str, bot_type: str = BOT_TYPE, limit: int = 50) -> list[dict]:
    """Questions eligible for reuse today: active, right bot_type, right
    subject, and either never used or past their next_global_review date.
    Scoring/ranking happens in scheduler/question_scheduler.py — this just
    returns the candidate set."""
    client = get_client()
    today = date.today().isoformat()
    res = (
        client.table("questions")
        .select("*")
        .eq("bot_type", bot_type)
        .eq("status", "active")
        .eq("subject", subject)
        .or_(f"next_global_review.is.null,next_global_review.lte.{today}")
        .limit(limit)
        .execute()
    )
    return res.data or []


def mark_used(question_id: str, usage_count: int, min_gap_days: int, max_gap_days: int) -> None:
    """Bump usage stats after a question is actually posted. The reuse gap
    grows with usage_count (a question asked many times gets rested longer),
    capped at max_gap_days so nothing disappears from rotation forever."""
    client = get_client()
    new_usage_count = usage_count + 1
    gap_days = min(min_gap_days * new_usage_count, max_gap_days)
    next_review = (date.today() + timedelta(days=gap_days)).isoformat()
    client.table("questions").update({
        "last_used_at": date.today().isoformat(),
        "usage_count": new_usage_count,
        "next_global_review": next_review,
    }).eq("id", question_id).execute()


def get_recent(bot_type: str = BOT_TYPE, days: int = 14) -> list[dict]:
    """Questions used in the last N days — feeds the "avoid repeating these"
    block of the Gemini prompt."""
    client = get_client()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    res = (
        client.table("questions")
        .select("subject, topic, question_text, last_used_at")
        .eq("bot_type", bot_type)
        .gte("last_used_at", cutoff)
        .execute()
    )
    return res.data or []


def get_used_on_date(target_date: date, bot_type: str = BOT_TYPE) -> list[dict]:
    """Questions whose last_used_at falls on an exact date — feeds the
    spaced-repetition resurfacing block of the Gemini prompt (3/7/14 days
    ago). Note: this reads last_used_at, which only reflects the *most
    recent* use of a question, so it's an approximation for questions used
    more than once — good enough for a prompt hint, not for scheduling
    decisions."""
    client = get_client()
    start = target_date.isoformat()
    end = (target_date + timedelta(days=1)).isoformat()
    res = (
        client.table("questions")
        .select("subject, topic, last_used_at")
        .eq("bot_type", bot_type)
        .gte("last_used_at", start)
        .lt("last_used_at", end)
        .execute()
    )
    return res.data or []


def subject_recent_usage(bot_type: str = BOT_TYPE) -> dict[str, int]:
    """Recent-use counts per subject, from the v_subject_recent_usage view —
    used by services/question_service.py to bias subject distribution away
    from over-used subjects instead of picking uniformly at random."""
    client = get_client()
    res = client.table("v_subject_recent_usage").select("subject, used_last_30_days").execute()
    return {row["subject"]: row.get("used_last_30_days", 0) or 0 for row in (res.data or [])}
