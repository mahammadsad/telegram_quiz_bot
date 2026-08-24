"""Progress-backed syllabus projection with explicit completion semantics."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from config.syllabus_catalog import CATALOGUE_ROWS
from models.user import User
from storage import syllabus_progress_repo, users_repo

MASTERY_SCORE = 80.0
MASTERY_ATTEMPTS = 2


def syllabus_progress(telegram_user: dict) -> dict:
    user_id = str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])
    return build_progress(
        syllabus_progress_repo.mapped_knowledge_points(),
        syllabus_progress_repo.micro_topics(),
        syllabus_progress_repo.user_mastery(user_id),
        today=datetime.now(ZoneInfo("Asia/Kolkata")).date(),
    )


def build_progress(
    knowledge_points: Iterable[dict[str, Any]],
    micro_topics: Iterable[dict[str, Any]],
    mastery_rows: Iterable[dict[str, Any]],
    *,
    today: date,
) -> dict[str, Any]:
    """Project coverage without treating unencountered content as mastered."""
    topic_key_by_id = {
        str(row.get("id")): str(row.get("key"))
        for row in micro_topics
        if row.get("id") and row.get("key")
    }
    valid_topics = {
        f"{subject}:{chapter_key}:t{index:02d}"
        for subject, chapters in CATALOGUE_ROWS.items()
        for chapter_key, _name, _priority, _rotation, topics in chapters
        for index, _topic in enumerate(topics, start=1)
    }
    point_topic: dict[str, str] = {}
    for row in knowledge_points:
        point_id = str(row.get("id") or "")
        topic_key = topic_key_by_id.get(str(row.get("micro_topic_id") or ""), "")
        subject = str(row.get("subject_key") or "")
        if point_id and topic_key in valid_topics and topic_key.startswith(f"{subject}:"):
            point_topic[point_id] = topic_key

    mastery = {
        str(row.get("knowledge_point_id")): row
        for row in mastery_rows
        if str(row.get("knowledge_point_id") or "") in point_topic
    }
    topic_points: dict[str, list[str]] = {key: [] for key in valid_topics}
    for point_id, topic_key in point_topic.items():
        topic_points[topic_key].append(point_id)

    subjects: list[dict[str, Any]] = []
    all_topic_metrics: list[dict[str, Any]] = []
    for subject, chapters in CATALOGUE_ROWS.items():
        projected_chapters: list[dict[str, Any]] = []
        subject_metrics: list[dict[str, Any]] = []
        for chapter_key, _name, _priority, _rotation, topics in chapters:
            chapter_full_key = f"{subject}:{chapter_key}"
            topic_metrics = [
                _topic_metric(
                    f"{chapter_full_key}:t{index:02d}",
                    topic_points[f"{chapter_full_key}:t{index:02d}"],
                    mastery,
                    today,
                )
                for index, _topic in enumerate(topics, start=1)
            ]
            projected_chapters.append({"key": chapter_full_key, **_aggregate(topic_metrics), "microTopics": topic_metrics})
            subject_metrics.extend(topic_metrics)
        subjects.append({"key": subject, **_aggregate(subject_metrics), "chapters": projected_chapters})
        all_topic_metrics.extend(subject_metrics)

    return {
        "version": 1,
        "asOf": today.isoformat(),
        "criteria": {
            "unit": "mapped_knowledge_point",
            "masteryScoreAtLeast": int(MASTERY_SCORE),
            "attemptsAtLeast": MASTERY_ATTEMPTS,
            "microTopicMasteredWhen": "all_mapped_knowledge_points_mastered",
            "unmappedContentExcludedFromMasteryDenominator": True,
            "diagnosticClaim": False,
        },
        "summary": _aggregate(all_topic_metrics),
        "subjects": subjects,
    }


def _topic_metric(
    topic_key: str,
    point_ids: list[str],
    mastery: dict[str, dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    mapped = len(point_ids)
    attempted = 0
    mastered = 0
    due = 0
    for point_id in point_ids:
        row = mastery.get(point_id)
        attempts = _integer(row.get("attempt_count") if row else 0)
        score = _number(row.get("mastery_score") if row else 0)
        if attempts > 0:
            attempted += 1
        if attempts >= MASTERY_ATTEMPTS and score >= MASTERY_SCORE:
            mastered += 1
        if attempts > 0 and _due(row.get("next_review") if row else None, today):
            due += 1
    status = "content_not_mapped"
    if mapped:
        status = "mastered" if mastered == mapped else "in_progress" if attempted else "not_started"
    return {
        "key": topic_key,
        "status": status,
        "mappedKnowledgePoints": mapped,
        "attemptedKnowledgePoints": attempted,
        "masteredKnowledgePoints": mastered,
        "dueKnowledgePoints": due,
        "coveragePercent": _percent(attempted, mapped),
        "masteryPercent": _percent(mastered, mapped),
    }


def _aggregate(topics: list[dict[str, Any]]) -> dict[str, Any]:
    mapped = sum(int(row["mappedKnowledgePoints"]) for row in topics)
    attempted = sum(int(row["attemptedKnowledgePoints"]) for row in topics)
    mastered = sum(int(row["masteredKnowledgePoints"]) for row in topics)
    due = sum(int(row["dueKnowledgePoints"]) for row in topics)
    mapped_topics = sum(int(row["mappedKnowledgePoints"] > 0) for row in topics)
    mastered_topics = sum(int(row["status"] == "mastered") for row in topics)
    return {
        "microTopicCount": len(topics),
        "mappedMicroTopicCount": mapped_topics,
        "masteredMicroTopicCount": mastered_topics,
        "mappedKnowledgePoints": mapped,
        "attemptedKnowledgePoints": attempted,
        "masteredKnowledgePoints": mastered,
        "dueKnowledgePoints": due,
        "contentMappedPercent": _percent(mapped_topics, len(topics)),
        "coveragePercent": _percent(attempted, mapped),
        "masteryPercent": _percent(mastered, mapped),
    }


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _due(value: object, today: date) -> bool:
    if not value:
        return False
    try:
        return date.fromisoformat(str(value)) <= today
    except ValueError:
        return False


def _percent(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 1) if denominator else 0.0
