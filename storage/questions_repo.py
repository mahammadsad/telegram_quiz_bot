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

from config.settings import BOT_TYPE, CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS, SIMILARITY_THRESHOLD
from database.client import get_client
from models.question import Question
from storage.contracts import Row, as_rows, first_row

LOG = logging.getLogger("storage.questions")


def get_by_id(question_id: str) -> Row | None:
    client = get_client()
    res = client.table("questions").select("*").eq("id", question_id).limit(1).execute()
    return first_row(res.data, "questions.by_id")


def get_by_hash(question_hash: str, bot_type: str = BOT_TYPE) -> Row | None:
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
    return first_row(res.data, "questions.by_hash")


def get_by_hash_any_bot(question_hash: str) -> Row | None:
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
    return first_row(res.data, "questions.by_hash_any_bot")


def get_by_content_hash(content_hash: str) -> Row | None:
    """Return only an exact immutable content-and-provenance version."""
    res = (
        get_client()
        .table("questions")
        .select("*")
        .eq("content_hash", content_hash)
        .limit(1)
        .execute()
    )
    return first_row(res.data, "questions.by_content_hash")


def get_latest_by_stem(stem_hash: str) -> Row | None:
    """Return the latest version of a stem without treating it as identical."""
    res = (
        get_client()
        .table("questions")
        .select("*")
        .eq("stem_hash", stem_hash)
        .order("content_version", desc=True)
        .limit(1)
        .execute()
    )
    return first_row(res.data, "questions.latest_by_stem")


def find_similar(normalized_text: str, bot_type: str = BOT_TYPE,
                  threshold: float = SIMILARITY_THRESHOLD, limit: int = 5) -> list[Row]:
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
    rows = as_rows(res.data, "similar questions")
    return [
        row
        for row in rows
        if isinstance(row.get("similarity"), (int, float))
        and float(row["similarity"]) >= threshold
    ]


def insert_question(question: Question) -> Row:
    client = get_client()
    res = client.table("questions").insert(question.to_insert_dict()).execute()
    row = first_row(res.data, "questions.insert")
    if row is None:
        raise RuntimeError("questions.insert returned no row")
    LOG.info("Inserted new question %s [%s/%s]", row["id"], row["subject"], row["topic"])
    return row


def get_eligible_pool(subject: str, bot_type: str = BOT_TYPE, limit: int = 50) -> list[Row]:
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
        .eq("verification_status", "verified")
        .eq("review_required", False)
        .eq("subject", subject)
        .or_(f"next_global_review.is.null,next_global_review.lte.{today}")
        .limit(limit)
        .execute()
    )
    rows = as_rows(res.data, "eligible question pool")
    current_cutoff = (date.today() - timedelta(days=CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS)).isoformat()
    return [
        row for row in rows
        if (not row.get("expires_at") or str(row["expires_at"])[:10] >= today)
        and (
            subject != "current-affairs"
            or bool(row.get("source_published_at") and str(row["source_published_at"])[:10] >= current_cutoff)
        )
    ]


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


def get_recent(bot_type: str = BOT_TYPE, days: int = 14) -> list[Row]:
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
    return as_rows(res.data, "recent questions")


def get_used_on_date(target_date: date, bot_type: str = BOT_TYPE) -> list[Row]:
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
    return as_rows(res.data, "questions used on date")


def subject_recent_usage(bot_type: str = BOT_TYPE) -> dict[str, int]:
    """Recent-use counts per subject, from the v_subject_recent_usage view —
    used by services/question_service.py to bias subject distribution away
    from over-used subjects instead of picking uniformly at random."""
    client = get_client()
    res = client.table("v_subject_recent_usage").select("subject, used_last_30_days").execute()
    rows = as_rows(res.data, "subject recent usage")
    result: dict[str, int] = {}
    for row in rows:
        subject = row.get("subject")
        count = row.get("used_last_30_days")
        if not isinstance(subject, str):
            raise RuntimeError("subject usage row has no subject")
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            raise RuntimeError("subject usage row has an invalid count")
        result[subject] = int(count)
    return result
