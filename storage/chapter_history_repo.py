"""Chapter-selection history persistence."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import Row, as_rows, first_row


def list_for_subject(subject_key: str, limit: int = 200) -> list[Row]:
    result = (
        get_client().table("chapter_history").select("*")
        .eq("subject_key", subject_key).order("selected_for", desc=True).limit(limit).execute()
    )
    return as_rows(result.data, "chapter history")


def record(subject_key: str, chapter: str, selected_for: str, quiz_id: str) -> None:
    client = get_client()
    existing = (
        client.table("chapter_history")
        .select("id")
        .eq("subject_key", subject_key)
        .eq("selected_for", selected_for)
        .limit(1)
        .execute()
    )
    payload = {
        "subject_key": subject_key,
        "chapter": chapter,
        "selected_for": selected_for,
        "quiz_id": quiz_id,
    }
    if first_row(existing.data, "chapter_history.record") is not None:
        (
            client.table("chapter_history")
            .update(payload)
            .eq("subject_key", subject_key)
            .eq("selected_for", selected_for)
            .execute()
        )
        return
    client.table("chapter_history").insert(payload).execute()
