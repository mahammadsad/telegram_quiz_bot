"""Strict numeric Telegram forum routing configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass

from config.subjects import QUIZ_SUBJECT_KEYS, get_subject

_DOCUMENTATION_EXAMPLE_IDS = {
    key: 101 + index for index, key in enumerate(QUIZ_SUBJECT_KEYS)
}


class ForumRoutingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ForumRouter:
    thread_ids: dict[str, int]
    general_thread_id: int | None = None

    @classmethod
    def from_values(cls, raw_json: str, general_thread_id: str | int | None = None) -> "ForumRouter":
        try:
            parsed = json.loads(raw_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ForumRoutingError("TELEGRAM_FORUM_TOPICS_JSON must be valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ForumRoutingError("TELEGRAM_FORUM_TOPICS_JSON must be a JSON object.")
        expected = set(QUIZ_SUBJECT_KEYS)
        actual = set(parsed)
        unknown = actual - expected
        missing = expected - actual
        if unknown:
            raise ForumRoutingError(f"Unknown subject keys in forum routing: {', '.join(sorted(unknown))}")
        if missing:
            raise ForumRoutingError(f"Missing forum thread IDs for: {', '.join(sorted(missing))}")
        clean: dict[str, int] = {}
        for key, value in parsed.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ForumRoutingError(f"Thread ID for {key} must be a positive integer.")
            clean[key] = value
        if len(set(clean.values())) != len(clean):
            raise ForumRoutingError("Forum thread IDs must be unique.")
        if clean == _DOCUMENTATION_EXAMPLE_IDS:
            raise ForumRoutingError(
                "The 101-113 forum mapping is documentation-only; discover real Telegram thread IDs."
            )
        return cls(clean, _optional_positive_int(general_thread_id))

    def for_subject(self, subject_key: str) -> int:
        get_subject(subject_key, require_quiz_enabled=True)
        try:
            return self.thread_ids[subject_key]
        except KeyError as exc:
            raise ForumRoutingError(f"No thread ID configured for {subject_key}.") from exc


def _optional_positive_int(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed
