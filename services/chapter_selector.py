"""Deterministic per-subject chapter selection with spaced review."""

from __future__ import annotations

from datetime import date

from config.settings import SPACED_REPETITION_OFFSETS
from config.subjects import get_subject
from config.syllabus import CHAPTERS
from storage import chapter_history_repo


def select_chapter(subject_key: str, target_date: date, history: list[dict] | None = None) -> str:
    get_subject(subject_key, require_quiz_enabled=True)
    catalogue = CHAPTERS.get(subject_key)
    if not catalogue:
        raise ValueError(f"No chapter catalogue configured for {subject_key}.")
    history = chapter_history_repo.list_for_subject(subject_key) if history is None else history
    normalized_history: list[tuple[str, date]] = []
    for row in history:
        chapter = str(row.get("chapter") or "")
        selected_for = _as_date(row.get("selected_for"))
        if chapter and selected_for:
            normalized_history.append((chapter, selected_for))
    normalized_history.sort(key=lambda item: item[1], reverse=True)
    used = {chapter for chapter, _ in normalized_history}
    last = normalized_history[0][0] if normalized_history else None

    for chapter in catalogue:
        if chapter not in used and chapter != last:
            return chapter

    due = []
    for chapter, used_on in normalized_history:
        if chapter == last:
            continue
        age = (target_date - used_on).days
        if age in SPACED_REPETITION_OFFSETS and chapter not in due:
            due.append(chapter)
    if due:
        return due[0]

    previous_dates: dict[str, date] = {}
    for chapter, used_on in normalized_history:
        previous_dates.setdefault(chapter, used_on)
    candidates = [chapter for chapter in catalogue if chapter != last]
    return min(candidates, key=lambda chapter: previous_dates.get(chapter, date.min))


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
