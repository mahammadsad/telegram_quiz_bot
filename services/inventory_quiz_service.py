"""Build due-time quiz packs from verified inventory before using Gemini."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import QUIZ_DIFFICULTY_DISTRIBUTION
from services.question_inventory import AssemblyResult, InventoryExhausted, assemble_verified_quiz
from services.question_validation import (
    QuizValidationError,
    validate_question_candidate,
    validate_questions,
)
from storage import content_inventory_repo

LOG = logging.getLogger("services.inventory_quiz")


@dataclass(frozen=True, slots=True)
class InventoryQuiz:
    questions: list[dict[str, Any]]
    relaxed_constraints: tuple[str, ...]
    source_ids: set[str]
    source_topics: dict[str, tuple[str, str]]


def load_verified_inventory_quiz(
    subject_key: str,
    chapter: str,
    *,
    now: datetime | None = None,
) -> InventoryQuiz | None:
    """Return a validated ten-question pack, or ``None`` for Gemini fallback."""
    current = _utc(now or datetime.now(timezone.utc))
    try:
        candidates = content_inventory_repo.list_verified_candidates(
            subject_key,
            now=current,
            limit=500,
        )
        chapter_candidates = [
            dict(row) for row in candidates if str(row.get("topic") or "") == chapter
        ]
        chapter_candidates, rejection_counts = _individually_valid_candidates(
            chapter_candidates,
            subject_key,
            chapter,
        )
        if rejection_counts:
            LOG.warning(
                "VERIFIED_INVENTORY_CANDIDATES_REJECTED subject=%s chapter=%s counts=%s",
                subject_key,
                chapter,
                dict(sorted(rejection_counts.items())),
            )
        history = content_inventory_repo.list_recent_usage(
            subject_key,
            since=current - timedelta(days=180),
        )
        assembled = assemble_verified_quiz(
            chapter_candidates,
            history,
            now=current,
            difficulty_targets=QUIZ_DIFFICULTY_DISTRIBUTION,
        )
        clean = _validate_assembled(assembled, subject_key, chapter)
    except (InventoryExhausted, QuizValidationError, RuntimeError, ValueError) as exc:
        LOG.info(
            "VERIFIED_INVENTORY_UNAVAILABLE subject=%s chapter=%s category=%s",
            subject_key,
            chapter,
            type(exc).__name__,
        )
        return None
    source_topics = {
        str(row["source_document_id"]): (
            str(row["micro_topic_id"]),
            str(row["micro_topic_key"]),
        )
        for row in clean
    }
    return InventoryQuiz(
        questions=clean,
        relaxed_constraints=assembled.relaxed_constraints,
        source_ids=set(source_topics),
        source_topics=source_topics,
    )


def _individually_valid_candidates(
    rows: list[dict[str, Any]],
    subject_key: str,
    chapter: str,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Remove stale invalid rows without discarding the remaining safe inventory."""
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for row in rows:
        try:
            candidate = _database_row_to_candidate(row)
            source_id = str(candidate.get("source_document_id") or "")
            source_topics = {
                source_id: (
                    str(candidate.get("micro_topic_id") or ""),
                    str(candidate.get("micro_topic_key") or ""),
                )
            }
            validate_question_candidate(
                candidate,
                subject_key,
                chapter,
                allowed_source_ids={source_id},
                allowed_source_topics=source_topics,
                require_verification=True,
            )
        except (QuizValidationError, RuntimeError, ValueError) as exc:
            rejected[getattr(exc, "reason_code", None) or type(exc).__name__] += 1
            continue
        valid.append(row)
    return valid, rejected


def _validate_assembled(
    assembled: AssemblyResult,
    subject_key: str,
    chapter: str,
) -> list[dict[str, Any]]:
    rows = [_database_row_to_candidate(row) for row in assembled.questions]
    source_topics = {
        str(row["source_document_id"]): (
            str(row["micro_topic_id"]),
            str(row["micro_topic_key"]),
        )
        for row in rows
    }
    return validate_questions(
        rows,
        subject_key,
        chapter,
        allowed_source_ids=set(source_topics),
        allowed_source_topics=source_topics,
        required_source_diversity=1,
        required_topic_diversity=1,
        require_verification=True,
    )


def _database_row_to_candidate(row: dict[str, Any]) -> dict[str, Any]:
    correct = str(row.get("correct_option") or "")
    if correct not in "ABCD":
        raise QuizValidationError("Inventory question has an invalid correct option.")
    return {
        "question_id": row.get("id"),
        "question": row.get("question_text"),
        "options": [
            row.get("option_a"),
            row.get("option_b"),
            row.get("option_c"),
            row.get("option_d"),
        ],
        "correct_index": "ABCD".index(correct),
        "explanation": row.get("explanation"),
        "detailed_explanation": row.get("detailed_explanation"),
        "subject_key": row.get("subject"),
        "chapter": row.get("topic"),
        "micro_topic_id": row.get("micro_topic_id"),
        "micro_topic_key": row.get("micro_topic_key"),
        "source_document_id": row.get("source_document_id"),
        "source_url": row.get("source_url"),
        "source_title": row.get("source_title"),
        "source_domain": row.get("source_domain"),
        "source_kind": row.get("source_kind"),
        "source_published_at": row.get("source_published_at"),
        "source_accessed_at": row.get("source_accessed_at"),
        "evidence_summary": row.get("evidence_summary"),
        "fact_version": row.get("fact_version"),
        "difficulty": row.get("difficulty"),
        "language": row.get("language"),
        "verification_status": row.get("verification_status"),
        "verification_score": row.get("verification_score"),
        "verification_notes": row.get("verification_notes"),
        "verification_checks": row.get("verification_checks") or {},
        "verified_at": row.get("verified_at"),
        "verification_model": row.get("verification_model"),
        "expires_at": row.get("expires_at"),
        "knowledge_point_id": row.get("knowledge_point_id"),
        "variant_fingerprint": row.get("variant_fingerprint"),
        "question_form": row.get("question_form") or "mcq",
        "inventory_status": row.get("inventory_status"),
        "eligible_at": row.get("eligible_at"),
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
