"""Question domain model — mirrors the `questions` table.

Kept as a plain dataclass rather than an ORM model: Supabase's Python
client speaks dicts over PostgREST, so a heavier ORM would just add a
translation layer without adding safety. This class exists to give the
rest of the codebase typed attribute access and a couple of small
convenience methods instead of passing raw dicts everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Question:
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str            # 'A' | 'B' | 'C' | 'D'
    subject: str
    topic: str
    question_hash: str
    normalized_text: str

    explanation: str = ""
    detailed_explanation: str = ""
    difficulty: str = "medium"
    gemini_model: Optional[str] = None
    source: str = "gemini_generated"
    week_number: Optional[int] = None
    bot_type: str = "daily_mcq"
    status: str = "active"
    micro_topic_id: Optional[str] = None
    micro_topic_key: Optional[str] = None
    source_document_id: Optional[str] = None
    verification_status: str = "generated"
    verification_score: Optional[float] = None
    verification_notes: str = ""
    verification_checks: Optional[dict[str, Any]] = None
    verified_at: Optional[str] = None
    verification_model: Optional[str] = None
    stem_hash: Optional[str] = None
    content_hash: Optional[str] = None
    content_version: Optional[int] = None
    supersedes_question_id: Optional[str] = None
    language: str = "bn"
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_domain: Optional[str] = None
    source_kind: Optional[str] = None
    source_published_at: Optional[str] = None
    source_accessed_at: Optional[str] = None
    evidence_summary: Optional[str] = None
    fact_version: Optional[str] = None
    expires_at: Optional[str] = None
    review_required: bool = False

    # scheduler metadata
    last_used_at: Optional[str] = None
    usage_count: int = 0
    next_global_review: Optional[str] = None
    selection_weight: float = 1.0
    quality_score: float = 1.0

    id: Optional[str] = None       # set once the row exists in the DB

    def options(self) -> list[str]:
        return [self.option_a, self.option_b, self.option_c, self.option_d]

    def correct_option_index(self) -> int:
        """0-based index — this is the format Telegram's sendPoll expects."""
        return "ABCD".index(self.correct_option)

    def to_insert_dict(self) -> dict:
        """Fields to write on INSERT. Omits `id` (DB-generated)."""
        return {
            "question_text": self.question_text,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "option_c": self.option_c,
            "option_d": self.option_d,
            "correct_option": self.correct_option,
            "explanation": self.explanation,
            "detailed_explanation": self.detailed_explanation,
            "subject": self.subject,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "gemini_model": self.gemini_model,
            "source": self.source,
            "week_number": self.week_number,
            "bot_type": self.bot_type,
            "question_hash": self.question_hash,
            "normalized_text": self.normalized_text,
            "status": self.status,
            "micro_topic_id": self.micro_topic_id,
            "micro_topic_key": self.micro_topic_key,
            "source_document_id": self.source_document_id,
            "verification_status": self.verification_status,
            "verification_score": self.verification_score,
            "verification_notes": self.verification_notes,
            "verification_checks": self.verification_checks or {},
            "verified_at": self.verified_at,
            "verification_model": self.verification_model,
            "stem_hash": self.stem_hash or self.question_hash,
            "content_hash": self.content_hash,
            "language": self.language,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "source_domain": self.source_domain,
            "source_kind": self.source_kind,
            "source_published_at": self.source_published_at,
            "source_accessed_at": self.source_accessed_at,
            "evidence_summary": self.evidence_summary,
            "fact_version": self.fact_version,
            "expires_at": self.expires_at,
            "review_required": self.review_required,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Question":
        return cls(
            id=row.get("id"),
            question_text=row["question_text"],
            option_a=row["option_a"],
            option_b=row["option_b"],
            option_c=row["option_c"],
            option_d=row["option_d"],
            correct_option=row["correct_option"],
            subject=row["subject"],
            topic=row["topic"],
            question_hash=row["question_hash"],
            normalized_text=row["normalized_text"],
            explanation=row.get("explanation") or "",
            detailed_explanation=row.get("detailed_explanation") or "",
            difficulty=row.get("difficulty", "medium"),
            gemini_model=row.get("gemini_model"),
            source=row.get("source", "gemini_generated"),
            week_number=row.get("week_number"),
            bot_type=row.get("bot_type", "daily_mcq"),
            status=row.get("status", "active"),
            micro_topic_id=row.get("micro_topic_id"),
            micro_topic_key=row.get("micro_topic_key"),
            source_document_id=row.get("source_document_id"),
            verification_status=row.get("verification_status", "generated"),
            verification_score=row.get("verification_score"),
            verification_notes=row.get("verification_notes") or "",
            verification_checks=row.get("verification_checks") or {},
            verified_at=row.get("verified_at"),
            verification_model=row.get("verification_model"),
            stem_hash=row.get("stem_hash") or row.get("question_hash"),
            content_hash=row.get("content_hash"),
            content_version=row.get("content_version"),
            supersedes_question_id=row.get("supersedes_question_id"),
            language=row.get("language") or "bn",
            source_url=row.get("source_url"),
            source_title=row.get("source_title"),
            source_domain=row.get("source_domain"),
            source_kind=row.get("source_kind"),
            source_published_at=row.get("source_published_at"),
            source_accessed_at=row.get("source_accessed_at"),
            evidence_summary=row.get("evidence_summary"),
            fact_version=row.get("fact_version"),
            expires_at=row.get("expires_at"),
            review_required=bool(row.get("review_required", False)),
            last_used_at=row.get("last_used_at"),
            usage_count=row.get("usage_count", 0),
            next_global_review=row.get("next_global_review"),
            selection_weight=row.get("selection_weight", 1.0),
            quality_score=row.get("quality_score", 1.0),
        )
