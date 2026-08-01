"""Fail-closed public projections for leaderboard RPC responses."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PRIVACY_MAINTENANCE_MESSAGE = (
    "ব্যক্তিগত তথ্য সুরক্ষার জন্য র‍্যাঙ্কিং সাময়িকভাবে বন্ধ আছে।"
)
NEUTRAL_ANONYMOUS_LABEL = "গোপন শিক্ষার্থী"

_IDENTITY_SOURCES = {
    "anonymous",
    "public_display_name",
    "public_username",
}
_ANONYMOUS_ALIAS = re.compile(r"^শিক্ষার্থী [0-9A-F]{12}$")
_PUBLIC_USERNAME = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

_TYPED_ROW_FIELDS = {
    "rank": ("rank",),
    "value": ("value",),
    "secondaryValue": ("secondaryValue", "secondary_value"),
    "totalAnswered": ("totalAnswered", "total_answered"),
    "correctAnswers": ("correctAnswers", "correct_answers"),
    "activityDays": ("activityDays", "activity_days"),
    "isCurrentUser": ("isCurrentUser", "is_current_user"),
}
_QUIZ_ROW_FIELDS = {
    "rank": ("rank",),
    "score": ("score",),
    "netScore": ("netScore", "net_score"),
    "negativeMarks": ("negativeMarks", "negative_marks"),
    "total": ("total",),
    "accuracy": ("accuracy",),
    "correct": ("correct",),
    "incorrect": ("incorrect",),
    "unanswered": ("unanswered",),
    "answered": ("answered",),
    "durationSeconds": ("durationSeconds", "duration_seconds"),
    "attemptsCount": ("attemptsCount", "attempts_count"),
    "percentile": ("percentile",),
    "rankMovement": ("rankMovement", "rank_movement"),
    "isCurrentUser": ("isCurrentUser", "is_current_user"),
}
_TYPED_TOP_LEVEL_FIELDS = {
    "type": ("type",),
    "subjectKey": ("subjectKey", "subject_key"),
    "participants": ("participants",),
    "limit": ("limit",),
    "offset": ("offset",),
    "separatorRequired": ("separatorRequired", "separator_required"),
    "tieBreak": ("tieBreak", "tie_break"),
    "rankingScope": ("rankingScope", "ranking_scope"),
    "retakesAffectOfficialRank": (
        "retakesAffectOfficialRank",
        "retakes_affect_official_rank",
    ),
    "practiceAffectsOfficialRank": (
        "practiceAffectsOfficialRank",
        "practice_affects_official_rank",
    ),
}
_QUIZ_TOP_LEVEL_FIELDS = {
    "quizId": ("quizId", "quiz_id"),
    "participants": ("participants",),
    "limit": ("limit",),
    "offset": ("offset",),
    "separatorRequired": ("separatorRequired", "separator_required"),
    "tieBreak": ("tieBreak", "tie_break"),
    "rankingScope": ("rankingScope", "ranking_scope"),
    "retakesAffectOfficialRank": (
        "retakesAffectOfficialRank",
        "retakes_affect_official_rank",
    ),
    "practiceAffectsOfficialRank": (
        "practiceAffectsOfficialRank",
        "practice_affects_official_rank",
    ),
}
_MARKING_SCHEME_FIELDS = {
    "rightMarks": ("rightMarks", "right_marks"),
    "wrongPenalty": ("wrongPenalty", "wrong_penalty"),
    "blankMarks": ("blankMarks", "blank_marks"),
    "negativeMarking": ("negativeMarking", "negative_marking"),
}


class LeaderboardPrivacyError(RuntimeError):
    """Raised when an RPC response cannot be projected without ambiguity."""


def project_typed_leaderboard(payload: object) -> dict[str, Any]:
    source = _mapping(payload)
    projected = _copy_scalars(source, _TYPED_TOP_LEVEL_FIELDS)
    projected["rows"] = _project_rows(source.get("rows"), _TYPED_ROW_FIELDS)
    projected["currentUser"] = _project_optional_row(
        source.get("currentUser", source.get("current_user")),
        _TYPED_ROW_FIELDS,
    )
    return projected


def project_quiz_leaderboard(payload: object) -> dict[str, Any]:
    source = _mapping(payload)
    projected = _copy_scalars(source, _QUIZ_TOP_LEVEL_FIELDS)
    projected["rows"] = _project_rows(source.get("rows"), _QUIZ_ROW_FIELDS)
    projected["currentUser"] = _project_optional_row(
        source.get("currentUser", source.get("current_user")),
        _QUIZ_ROW_FIELDS,
    )
    marking = source.get("markingScheme", source.get("marking_scheme"))
    if marking is not None:
        projected["markingScheme"] = _copy_scalars(
            _mapping(marking),
            _MARKING_SCHEME_FIELDS,
        )
    return projected


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LeaderboardPrivacyError("untrusted leaderboard response shape")
    return value


def _project_rows(
    value: object,
    allowed_fields: Mapping[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LeaderboardPrivacyError("untrusted leaderboard rows shape")
    return [_project_row(_mapping(row), allowed_fields) for row in value]


def _project_optional_row(
    value: object,
    allowed_fields: Mapping[str, tuple[str, ...]],
) -> dict[str, Any] | None:
    if value is None:
        return None
    return _project_row(_mapping(value), allowed_fields)


def _project_row(
    source: Mapping[str, Any],
    allowed_fields: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    projected = _copy_scalars(source, allowed_fields)
    label, identity_source = _safe_public_label(source)
    projected["displayName"] = label
    projected["initials"] = _safe_initials(label, identity_source)
    return projected


def _copy_scalars(
    source: Mapping[str, Any],
    fields: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for output_key, input_keys in fields.items():
        for input_key in input_keys:
            if input_key not in source:
                continue
            value = source[input_key]
            if value is None or isinstance(value, (str, int, float, bool)):
                projected[output_key] = value
            break
    return projected


def _safe_public_label(source: Mapping[str, Any]) -> tuple[str, str]:
    identity_source = source.get("identitySource", source.get("identity_source"))
    raw_label = source.get("displayName", source.get("display_name"))
    if identity_source not in _IDENTITY_SOURCES or not isinstance(raw_label, str):
        return NEUTRAL_ANONYMOUS_LABEL, "anonymous"

    label = raw_label.strip()
    if identity_source == "anonymous":
        if _ANONYMOUS_ALIAS.fullmatch(label):
            return label, identity_source
    elif identity_source == "public_username":
        if _PUBLIC_USERNAME.fullmatch(label):
            return label, identity_source
    elif (
        2 <= len(label) <= 40
        and not _CONTROL_CHARACTERS.search(label)
    ):
        return label, identity_source
    return NEUTRAL_ANONYMOUS_LABEL, "anonymous"


def _safe_initials(label: str, identity_source: str) -> str:
    if identity_source == "anonymous":
        return "শি"
    candidate = label[1:] if label.startswith("@") else label
    return candidate[:1].upper() or "শি"
