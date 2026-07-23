"""
Text normalization + hashing for duplicate detection.

Three-layer duplicate detection strategy (per project spec):
    1. question_hash   -> exact-duplicate lookup (unique DB constraint, O(1))
    2. normalized_text -> cheap textual comparison / debugging
    3. similarity       -> fuzzy near-duplicate search via Postgres pg_trgm
                            (see database/schema.sql: find_similar_questions)

Layers 1-2 are computed here in Python. Layer 3 is delegated to Postgres
because trigram similarity search over a growing question bank does not
scale if done client-side in Python.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

# Collapse any run of whitespace to a single space.
_WHITESPACE_RE = re.compile(r"\s+")

# Strip common punctuation, including the Bengali daŗi/danda "।" and other
# Bengali-context punctuation, so that trivial punctuation differences don't
# defeat exact-duplicate detection.
_PUNCT_RE = re.compile(r"[।,.!?\"'‘’“”:;()\[\]{}—–\-]+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace.

    This is intentionally aggressive: it's used purely for duplicate
    detection, never for display. Two questions that are identical except
    for punctuation or casing should normalize to the same string.
    """
    text = (text or "").strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def question_hash(question_text: str) -> str:
    """SHA-256 hex digest of the normalized question text.

    Used as a unique DB constraint (questions.question_hash) to reject
    exact/near-exact duplicates in O(1) at insert time.
    """
    normalized = normalize_text(question_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# The order is part of the persisted database contract. Keep this list aligned
# with public.question_content_hash(jsonb) in the latest Supabase migration.
QUESTION_CONTENT_FIELDS = (
    "question_text",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "correct_option",
    "explanation",
    "detailed_explanation",
    "subject",
    "topic",
    "micro_topic_key",
    "difficulty",
    "language",
    "source_document_id",
    "source_url",
    "source_title",
    "source_domain",
    "source_kind",
    "source_published_at",
    "source_accessed_at",
    "evidence_summary",
    "fact_version",
    "verification_status",
    "verification_score",
    "verification_notes",
    "verified_at",
    "verification_model",
)


def canonical_content_text(value: Any) -> str:
    """Normalize display content without discarding punctuation or case."""
    return _WHITESPACE_RE.sub(" ", str(value or "").strip())


def canonical_content_timestamp(value: Any) -> str:
    """Return the exact UTC timestamp representation used by PostgreSQL."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid content timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_content_score(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    try:
        return f"{Decimal(text):.6f}"
    except InvalidOperation as exc:
        raise ValueError("invalid verification score") from exc


def content_hash_part(name: str, value: Any) -> str:
    text = str(value or "")
    return f"{name}:{len(text.encode('utf-8'))}:{text}\n"


def question_content_values(question: Mapping[str, Any]) -> dict[str, str]:
    """Project generated or database-shaped content into the hash contract."""
    options = question.get("options", question.get("o"))
    if not isinstance(options, list):
        options = [
            question.get("option_a"),
            question.get("option_b"),
            question.get("option_c"),
            question.get("option_d"),
        ]
    options = [*options, None, None, None, None][:4]
    correct_option = question.get("correct_option")
    if not correct_option:
        index = question.get("correct_index", question.get("a"))
        correct_option = "ABCD"[index] if isinstance(index, int) and index in range(4) else ""

    values: dict[str, str] = {
        "question_text": canonical_content_text(
            question.get("question_text", question.get("question", question.get("q")))
        ),
        "option_a": canonical_content_text(options[0]),
        "option_b": canonical_content_text(options[1]),
        "option_c": canonical_content_text(options[2]),
        "option_d": canonical_content_text(options[3]),
        "correct_option": str(correct_option or "").strip().upper(),
        "explanation": canonical_content_text(
            question.get("explanation", question.get("e"))
        ),
        "detailed_explanation": canonical_content_text(
            question.get("detailed_explanation", question.get("detailedExplanation"))
        ),
        "subject": str(
            question.get("subject", question.get("subject_key", "")) or ""
        ).strip().lower(),
        "topic": canonical_content_text(
            question.get("topic", question.get("chapter", ""))
        ),
        "micro_topic_key": str(question.get("micro_topic_key") or "").strip().lower(),
        "difficulty": str(question.get("difficulty") or "").strip().lower(),
        "language": str(question.get("language") or "bn").strip().lower(),
        "source_document_id": str(question.get("source_document_id") or "").strip().lower(),
        "source_url": str(question.get("source_url") or "").strip(),
        "source_title": canonical_content_text(question.get("source_title")),
        "source_domain": str(question.get("source_domain") or "").strip().lower(),
        "source_kind": str(question.get("source_kind") or "").strip().lower(),
        "source_published_at": canonical_content_timestamp(
            question.get("source_published_at")
        ),
        "source_accessed_at": canonical_content_timestamp(
            question.get("source_accessed_at")
        ),
        "evidence_summary": canonical_content_text(question.get("evidence_summary")),
        "fact_version": canonical_content_text(question.get("fact_version")),
        "verification_status": str(question.get("verification_status") or "").strip().lower(),
        "verification_score": canonical_content_score(question.get("verification_score")),
        "verification_notes": canonical_content_text(question.get("verification_notes")),
        "verified_at": canonical_content_timestamp(question.get("verified_at")),
        "verification_model": canonical_content_text(question.get("verification_model")),
    }
    return values


def question_content_hash(question: Mapping[str, Any]) -> str:
    values = question_content_values(question)
    payload = "".join(content_hash_part(name, values[name]) for name in QUESTION_CONTENT_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def quiz_content_checksum(
    quiz_id: str,
    subject_key: str,
    chapter: str,
    questions: Sequence[Mapping[str, Any]],
) -> str:
    payload = (
        content_hash_part("quiz_id", str(quiz_id).strip())
        + content_hash_part("subject_key", str(subject_key).strip().lower())
        + content_hash_part("chapter", canonical_content_text(chapter))
        + "".join(
            content_hash_part(f"question_{index}", question_content_hash(question))
            for index, question in enumerate(questions, start=1)
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
