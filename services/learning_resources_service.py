"""Public projection of cached learning resources for a quiz pack."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from storage import learning_resources_repo


def public_resources_for_quiz(quiz_id: str) -> dict:
    rows = learning_resources_repo.list_for_quiz(quiz_id, limit_per_language=3)
    topics: OrderedDict[str, dict] = OrderedDict()

    for row in rows:
        micro_topic_key = _text(row.get("micro_topic_key"))
        if not micro_topic_key:
            continue
        topic = topics.setdefault(
            micro_topic_key,
            {
                "subjectKey": _text(row.get("subject_key")),
                "subject": _text(row.get("subject_name")),
                "chapterKey": _text(row.get("chapter_key")),
                "chapter": _text(row.get("chapter_name")),
                "microTopicKey": micro_topic_key,
                "microTopic": _text(row.get("micro_topic_name")),
                "resources": [],
            },
        )
        resource_id = _text(row.get("resource_id"))
        url = _text(row.get("url"))
        if not resource_id or not url.startswith("https://"):
            continue
        topic["resources"].append({
            "id": resource_id,
            "language": _text(row.get("language")),
            "type": _text(row.get("resource_type")),
            "title": _text(row.get("title")),
            "url": url,
            "source": _text(row.get("source_name")),
            "domain": _text(row.get("source_domain")),
            "youtubeVideoId": _nullable_text(row.get("youtube_video_id")),
            "durationSeconds": row.get("duration_seconds"),
            "thumbnailUrl": _nullable_text(row.get("thumbnail_url")),
            "description": _nullable_text(row.get("description")),
            "publishedAt": _nullable_text(row.get("published_at")),
        })

    topic_rows = list(topics.values())
    resource_count = sum(len(topic["resources"]) for topic in topic_rows)
    return {
        "quizId": quiz_id,
        "available": resource_count > 0,
        "topics": topic_rows,
        "policy": {
            "cachedOnly": True,
            "verifiedOnly": True,
            "maxPerLanguagePerTopic": 3,
        },
    }


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _nullable_text(value: Any) -> str | None:
    clean = _text(value)
    return clean or None
