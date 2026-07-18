"""Quota-bounded YouTube candidate discovery for missing Bengali/Hindi resources."""

from __future__ import annotations

import argparse
import os
import re
from typing import Any

import requests

from storage import resource_quality_repo

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)
CLICKBAIT_TERMS = ("100% common", "leak", "guaranteed", "viral", "must watch")


def build_query(language: str, micro_topic: str) -> str:
    suffix = "competitive exam Bengali" if language == "bn" else "competitive exam Hindi"
    return f"{micro_topic.strip()} {suffix}"


def parse_duration(value: str) -> int | None:
    match = ISO_DURATION.fullmatch(value or "")
    if not match:
        return None
    parts = {key: int(raw or 0) for key, raw in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def discover_candidate(
    item: dict,
    *,
    api_key: str,
    policies: dict[str, str],
    session: requests.Session,
) -> dict[str, Any] | None:
    language = str(item["language"])
    search = session.get(
        f"{YOUTUBE_API}/search",
        params={
            "part": "snippet",
            "q": build_query(language, str(item["micro_topic_name"])),
            "type": "video",
            "maxResults": 5,
            "relevanceLanguage": language,
            "safeSearch": "strict",
            "videoEmbeddable": "true",
            "key": api_key,
        },
        timeout=30,
    )
    search.raise_for_status()
    search_rows = search.json().get("items") or []
    video_ids = [
        str(row.get("id", {}).get("videoId") or "")
        for row in search_rows
        if row.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return None
    details = session.get(
        f"{YOUTUBE_API}/videos",
        params={
            "part": "snippet,contentDetails,status",
            "id": ",".join(video_ids),
            "key": api_key,
        },
        timeout=30,
    )
    details.raise_for_status()
    ranked: list[tuple[float, float, dict[str, Any]]] = []
    topic_words = {
        word.casefold() for word in str(item["micro_topic_name"]).split() if len(word) > 2
    }
    for row in details.json().get("items") or []:
        snippet = row.get("snippet") or {}
        status = row.get("status") or {}
        video_id = str(row.get("id") or "")
        channel_id = str(snippet.get("channelId") or "")
        if (
            len(video_id) != 11
            or status.get("privacyStatus") != "public"
            or status.get("embeddable") is False
            or policies.get(channel_id) == "blocked"
        ):
            continue
        duration = parse_duration(str((row.get("contentDetails") or {}).get("duration") or ""))
        if duration is None or not 120 <= duration <= 10800:
            continue
        title = str(snippet.get("title") or "").strip()
        title_words = {word.casefold() for word in title.split() if len(word) > 2}
        overlap = len(topic_words & title_words) / max(1, len(topic_words))
        relevance = min(0.98, 0.72 + 0.20 * overlap)
        quality = 0.68
        if policies.get(channel_id) == "preferred":
            quality += 0.22
        elif policies.get(channel_id) == "trusted":
            quality += 0.12
        if any(term in title.casefold() for term in CLICKBAIT_TERMS):
            quality -= 0.20
        thumbnails = snippet.get("thumbnails") or {}
        thumbnail = (thumbnails.get("high") or thumbnails.get("medium") or {}).get("url")
        payload = {
            "p_title": title[:300],
            "p_url": f"https://www.youtube.com/watch?v={video_id}",
            "p_source_name": str(snippet.get("channelTitle") or "YouTube")[:160],
            "p_channel_id": channel_id,
            "p_video_id": video_id,
            "p_duration_seconds": duration,
            "p_thumbnail_url": thumbnail,
            "p_description": str(snippet.get("description") or "")[:500] or None,
            "p_published_at": snippet.get("publishedAt"),
            "p_quality_score": round(max(0, min(1, quality)), 2),
            "p_relevance_score": round(relevance, 2),
        }
        ranked.append((relevance, quality, payload))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return ranked[0][2]


def run(*, limit: int, api_key: str) -> dict[str, int]:
    queued = resource_quality_repo.queue_missing_resources(limit=200)
    summary = {"queued": queued, "processed": 0, "candidates": 0, "failed": 0}
    if not api_key:
        return summary
    policies = {
        str(row["channel_id"]): str(row["policy"])
        for row in resource_quality_repo.channel_policies()
    }
    session = requests.Session()
    for item in resource_quality_repo.discovery_batch(limit=limit):
        queue_id = str(item["queue_id"])
        summary["processed"] += 1
        try:
            candidate = discover_candidate(
                item,
                api_key=api_key,
                policies=policies,
                session=session,
            )
            if not candidate:
                resource_quality_repo.complete_discovery(queue_id, outcome="no_candidate")
                summary["failed"] += 1
                continue
            resource_quality_repo.save_youtube_candidate(queue_id, candidate)
            summary["candidates"] += 1
        except requests.RequestException:
            resource_quality_repo.complete_discovery(
                queue_id,
                outcome="transient_error",
                error_category="youtube_api_unavailable",
            )
            summary["failed"] += 1
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover pending YouTube resources")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    summary = run(limit=max(1, min(args.limit, 20)), api_key=api_key)
    if not api_key:
        print("youtube_discovery=disabled optional_key_configured=false")
    print(" ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
