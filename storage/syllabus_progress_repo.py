"""Read-only persistence for learner progress against mapped syllabus units."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import Row, StorageContractError, as_rows

PAGE_SIZE = 1000
MAX_ROWS = 5000


def mapped_knowledge_points() -> list[Row]:
    return _paged(
        "knowledge_points",
        "id,subject_key,micro_topic_id",
        filters=(("status", "active"), ("syllabus_status", "mapped")),
    )


def micro_topics() -> list[Row]:
    return _paged(
        "quiz_micro_topics",
        "id,key",
        filters=(("active", True),),
    )


def user_mastery(user_id: str) -> list[Row]:
    return _paged(
        "personal_knowledge_mastery",
        "knowledge_point_id,attempt_count,mastery_score,next_review",
        filters=(("user_id", user_id),),
    )


def _paged(table: str, fields: str, *, filters: tuple[tuple[str, object], ...]) -> list[Row]:
    rows: list[Row] = []
    for offset in range(0, MAX_ROWS, PAGE_SIZE):
        query = get_client().table(table).select(fields)
        for field, value in filters:
            query = query.eq(field, value)
        result = query.order("id" if table != "personal_knowledge_mastery" else "knowledge_point_id").range(
            offset, offset + PAGE_SIZE - 1
        ).execute()
        page = as_rows(result.data, f"{table} syllabus progress")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        if offset + PAGE_SIZE >= MAX_ROWS:
            raise StorageContractError(f"{table} exceeded the safe syllabus-progress row bound")
    return rows
