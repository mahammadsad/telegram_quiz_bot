"""Canonical and legacy quiz ID helpers."""

from __future__ import annotations

import re
from datetime import date

from config.subjects import get_subject

_CANONICAL_RE = re.compile(r"^(\d{8})-([a-z0-9]+(?:-[a-z0-9]+)*)$")
_LEGACY_RE = re.compile(r"^\d{8}$")


def build_quiz_id(target_date: date, subject_key: str) -> str:
    get_subject(subject_key, require_quiz_enabled=True)
    return f"{target_date:%Y%m%d}-{subject_key}"


def parse_quiz_id(quiz_id: str, *, allow_legacy: bool = True) -> tuple[date, str | None]:
    match = _CANONICAL_RE.fullmatch(quiz_id)
    if match:
        parsed_date = _parse_date(match.group(1))
        subject_key = match.group(2)
        get_subject(subject_key, require_quiz_enabled=True)
        return parsed_date, subject_key
    if allow_legacy and _LEGACY_RE.fullmatch(quiz_id):
        return _parse_date(quiz_id), None
    raise ValueError("Invalid quiz id; expected YYYYMMDD-<canonical-subject-key>.")


def _parse_date(value: str) -> date:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise ValueError("Invalid date in quiz id.") from exc
