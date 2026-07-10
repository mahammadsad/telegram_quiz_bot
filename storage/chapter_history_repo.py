"""Chapter-selection history persistence."""

from __future__ import annotations

from database.client import get_client


def list_for_subject(subject_key: str, limit: int = 200) -> list[dict]:
    result = (
        get_client().table("chapter_history").select("*")
        .eq("subject_key", subject_key).order("selected_for", desc=True).limit(limit).execute()
    )
    return result.data or []


def record(subject_key: str, chapter: str, selected_for: str, quiz_id: str) -> None:
    get_client().table("chapter_history").upsert({
        "subject_key": subject_key,
        "chapter": chapter,
        "selected_for": selected_for,
        "quiz_id": quiz_id,
    }, on_conflict="subject_key,selected_for").execute()
