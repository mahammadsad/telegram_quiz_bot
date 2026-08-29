"""Verified question inventory reporting and soft-policy assembly."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from config.settings import (
    CONTENT_CHAPTER_COOLDOWN_DAYS,
    CONTENT_EXACT_VARIANT_COOLDOWN_DAYS,
    CONTENT_INVENTORY_BATCH_SIZE,
    CONTENT_INVENTORY_TARGET_DAYS,
    CONTENT_KNOWLEDGE_POINT_COOLDOWN_DAYS,
    CONTENT_MAX_QUIZ_OVERLAP_RATIO,
    CONTENT_MICRO_TOPIC_COOLDOWN_DAYS,
    CONTENT_QUIZ_OVERLAP_WINDOW_DAYS,
    CONTENT_SEMANTIC_NEAR_COOLDOWN_DAYS,
    CONTENT_SOURCE_COOLDOWN_DAYS,
    CONTENT_TOPIC_COOLDOWN_DAYS,
)

QUESTION_COUNT = 10


class InventoryExhausted(RuntimeError):
    """Raised only when fewer than ten correctness-safe candidates exist."""


@dataclass(frozen=True, slots=True)
class RotationPolicy:
    chapter_days: int = CONTENT_CHAPTER_COOLDOWN_DAYS
    topic_days: int = CONTENT_TOPIC_COOLDOWN_DAYS
    micro_topic_days: int = CONTENT_MICRO_TOPIC_COOLDOWN_DAYS
    source_days: int = CONTENT_SOURCE_COOLDOWN_DAYS
    knowledge_point_days: int = CONTENT_KNOWLEDGE_POINT_COOLDOWN_DAYS
    exact_variant_days: int = CONTENT_EXACT_VARIANT_COOLDOWN_DAYS
    semantic_near_days: int = CONTENT_SEMANTIC_NEAR_COOLDOWN_DAYS
    quiz_overlap_days: int = CONTENT_QUIZ_OVERLAP_WINDOW_DAYS
    max_quiz_overlap_ratio: float = CONTENT_MAX_QUIZ_OVERLAP_RATIO


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    questions: list[dict[str, Any]]
    relaxed_constraints: tuple[str, ...]
    selected_with_relaxation: dict[str, tuple[str, ...]]


_RELAXATION_ORDER = (
    "quiz_overlap",
    "chapter",
    "topic",
    "micro_topic",
    "source",
    "semantic_near",
    "knowledge_point",
    "exact_variant",
    "eligible_at",
)


def assemble_verified_quiz(
    candidates: Iterable[dict[str, Any]],
    recent_usage: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    count: int = QUESTION_COUNT,
    policy: RotationPolicy | None = None,
    difficulty_targets: Mapping[str, int] | None = None,
) -> AssemblyResult:
    """Select the oldest safe inventory, relaxing rotation only as needed."""
    current = _utc(now or datetime.now(timezone.utc))
    rules = policy or RotationPolicy()
    safe = [dict(row) for row in candidates if _is_safety_eligible(row, current)]
    if len(safe) < count:
        raise InventoryExhausted(f"Only {len(safe)} verified, supported candidates are available; {count} required.")
    targets = Counter(difficulty_targets or {})
    if targets:
        if any(value < 0 for value in targets.values()) or sum(targets.values()) != count:
            raise ValueError("Difficulty targets must be non-negative and total the requested quiz size.")
        available = Counter(str(row.get("difficulty") or "") for row in safe)
        shortages = {
            difficulty: required - available[difficulty]
            for difficulty, required in targets.items()
            if available[difficulty] < required
        }
        if shortages:
            raise InventoryExhausted(
                f"Verified inventory cannot satisfy difficulty targets; shortages={shortages}."
            )
    ordered = sorted(safe, key=_candidate_order)
    history = [dict(row) for row in recent_usage]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    selected_with_relaxation: dict[str, tuple[str, ...]] = {}
    relaxed: set[str] = set()

    for stage in range(len(_RELAXATION_ORDER) + 1):
        allowed = set(_RELAXATION_ORDER[:stage])
        for candidate in ordered:
            candidate_id = _candidate_id(candidate)
            if candidate_id in selected_ids:
                continue
            difficulty = str(candidate.get("difficulty") or "")
            if targets and (
                difficulty not in targets
                or sum(
                    1 for row in selected if row.get("difficulty") == difficulty
                )
                >= targets[difficulty]
            ):
                continue
            violations = _rotation_violations(
                candidate,
                history,
                selected,
                current,
                rules,
            )
            if not violations.issubset(allowed):
                continue
            selected.append(candidate)
            selected_ids.add(candidate_id)
            used_relaxations = tuple(name for name in _RELAXATION_ORDER if name in violations)
            selected_with_relaxation[candidate_id] = used_relaxations
            relaxed.update(used_relaxations)
            if len(selected) == count:
                return AssemblyResult(
                    questions=selected,
                    relaxed_constraints=tuple(name for name in _RELAXATION_ORDER if name in relaxed),
                    selected_with_relaxation=selected_with_relaxation,
                )
    raise InventoryExhausted("Verified inventory could not fill the requested quiz size.")


def inventory_report(
    candidates: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    questions_per_day: int = QUESTION_COUNT,
) -> dict[str, dict[str, float | int]]:
    """Return safe and immediately eligible inventory days per subject."""
    current = _utc(now or datetime.now(timezone.utc))
    counts: dict[str, dict[str, int]] = {}
    for row in candidates:
        if not _is_safety_eligible(row, current):
            continue
        subject = str(row.get("subject") or row.get("subject_key") or "").strip()
        if not subject:
            continue
        bucket = counts.setdefault(subject, {"verified": 0, "eligible_now": 0})
        bucket["verified"] += 1
        eligible_at = _parse_time(row.get("eligible_at"))
        if eligible_at is None or eligible_at <= current:
            bucket["eligible_now"] += 1
    return {
        subject: {
            **values,
            "verified_days": round(values["verified"] / questions_per_day, 2),
            "eligible_days": round(values["eligible_now"] / questions_per_day, 2),
        }
        for subject, values in sorted(counts.items())
    }


def replenishment_plan(
    verified_count: int,
    *,
    target_days: int = CONTENT_INVENTORY_TARGET_DAYS,
    questions_per_day: int = QUESTION_COUNT,
    batch_size: int = CONTENT_INVENTORY_BATCH_SIZE,
) -> dict[str, int]:
    """Plan small 3–5 candidate batches toward a 12–15 day surplus."""
    if target_days not in range(12, 16):
        raise ValueError("target_days must be between 12 and 15")
    if batch_size not in range(3, 6):
        raise ValueError("batch_size must be between 3 and 5")
    target = target_days * questions_per_day
    missing = max(0, target - max(0, verified_count))
    return {
        "verified_count": max(0, verified_count),
        "target_count": target,
        "missing_count": missing,
        "batch_size": batch_size,
        "batch_count": (missing + batch_size - 1) // batch_size,
    }


def exposure_quality_report(
    usage_events: Iterable[dict[str, Any]],
    *,
    repeat_target_percent: float = 0.5,
) -> dict[str, float | int | bool]:
    """Measure repeated learner exposure without returning question content."""
    events = [dict(event) for event in usage_events]
    question_counts: dict[str, int] = {}
    quiz_question_counts: dict[tuple[str, str], int] = {}
    unidentified = 0
    for event in events:
        question_id = str(event.get("question_id") or event.get("variant_fingerprint") or "").strip()
        if not question_id:
            unidentified += 1
            continue
        question_counts[question_id] = question_counts.get(question_id, 0) + 1
        quiz_id = str(event.get("quiz_id") or "").strip()
        if quiz_id:
            key = (quiz_id, question_id)
            quiz_question_counts[key] = quiz_question_counts.get(key, 0) + 1

    identified_events = sum(question_counts.values())
    repeated_events = sum(max(0, count - 1) for count in question_counts.values())
    repeated_rate = round((repeated_events / identified_events) * 100, 4) if identified_events else 0.0
    same_quiz_duplicate_events = sum(max(0, count - 1) for count in quiz_question_counts.values())
    return {
        "total_events": len(events),
        "identified_events": identified_events,
        "unidentified_events": unidentified,
        "unique_questions": len(question_counts),
        "repeated_questions": sum(1 for count in question_counts.values() if count > 1),
        "repeated_events": repeated_events,
        "repeated_exposure_percent": repeated_rate,
        "same_quiz_duplicate_events": same_quiz_duplicate_events,
        "passes_repeat_target": repeated_rate < repeat_target_percent,
        "passes_same_quiz_target": same_quiz_duplicate_events == 0,
    }


def _is_safety_eligible(row: dict[str, Any], now: datetime) -> bool:
    expires_at = _parse_time(row.get("expires_at"))
    return (
        row.get("status") == "active"
        and row.get("verification_status") == "verified"
        and not bool(row.get("review_required"))
        and row.get("inventory_status") in {"verified", "used"}
        and bool(row.get("knowledge_point_id"))
        and bool(row.get("variant_fingerprint"))
        and bool(row.get("source_document_id"))
        and (expires_at is None or expires_at >= now)
        and row.get("source_verification_status", "verified") == "verified"
        and row.get("source_fact_verification_status", "verified") == "verified"
        and not bool(row.get("source_review_required"))
        and not bool(row.get("source_fact_review_required"))
    )


def _rotation_violations(
    candidate: dict[str, Any],
    history: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    now: datetime,
    policy: RotationPolicy,
) -> set[str]:
    violations: set[str] = set()
    eligible_at = _parse_time(candidate.get("eligible_at"))
    if eligible_at is not None and eligible_at > now:
        violations.add("eligible_at")
    dimensions = (
        ("chapter", "chapter", policy.chapter_days),
        ("topic", "topic_key", policy.topic_days),
        ("micro_topic", "micro_topic_id", policy.micro_topic_days),
        ("source", "source_document_id", policy.source_days),
        ("knowledge_point", "knowledge_point_id", policy.knowledge_point_days),
        ("exact_variant", "variant_fingerprint", policy.exact_variant_days),
        ("semantic_near", "semantic_cluster_id", policy.semantic_near_days),
    )
    for constraint, field, days in dimensions:
        value = candidate.get(field)
        if not value:
            continue
        cutoff = now - timedelta(days=days)
        if any(
            event.get(field) == value
            and (_parse_time(event.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
            for event in history
        ):
            violations.add(constraint)

    overlap_cutoff = now - timedelta(days=policy.quiz_overlap_days)
    prior_quiz_counts: dict[str, int] = {}
    candidate_id = _candidate_id(candidate)
    for event in history:
        occurred_at = _parse_time(event.get("occurred_at"))
        quiz_id = str(event.get("quiz_id") or "")
        if not quiz_id or occurred_at is None or occurred_at < overlap_cutoff:
            continue
        if str(event.get("question_id") or "") == candidate_id:
            prior_quiz_counts[quiz_id] = prior_quiz_counts.get(quiz_id, 0) + 1
    max_overlap = max(1, int(QUESTION_COUNT * policy.max_quiz_overlap_ratio))
    for chosen in selected:
        chosen_id = _candidate_id(chosen)
        for event in history:
            quiz_id = str(event.get("quiz_id") or "")
            if quiz_id in prior_quiz_counts and str(event.get("question_id") or "") == chosen_id:
                prior_quiz_counts[quiz_id] += 1
    if any(value > max_overlap for value in prior_quiz_counts.values()):
        violations.add("quiz_overlap")
    return violations


def _candidate_order(row: dict[str, Any]) -> tuple[Any, ...]:
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    return (
        _parse_time(row.get("eligible_at")) or earliest,
        int(row.get("usage_count") or 0),
        _parse_time(row.get("last_used_at")) or earliest,
        _parse_time(row.get("created_at")) or earliest,
        _candidate_id(row),
    )


def _candidate_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("question_id") or row.get("variant_fingerprint") or "")


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
