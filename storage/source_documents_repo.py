"""Verified source bundles and normalized micro-topic usage."""

from __future__ import annotations

from database.client import get_client


def list_grounding_bundle(
    subject_key: str,
    chapter: str,
    target_date: str,
    *,
    limit: int = 8,
) -> list[dict]:
    result = get_client().rpc(
        "get_grounding_bundle",
        {
            "p_subject_key": subject_key,
            "p_chapter": chapter,
            "p_target_date": target_date,
            "p_limit": limit,
        },
    ).execute()
    return result.data or []


def mark_micro_topic_used(micro_topic_id: str, used_at: str) -> None:
    get_client().table("quiz_micro_topics").update({
        "last_used_at": used_at,
    }).eq("id", micro_topic_id).execute()

