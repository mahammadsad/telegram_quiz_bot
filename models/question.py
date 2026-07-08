"""Question domain model — mirrors the `questions` table.

Kept as a plain dataclass rather than an ORM model: Supabase's Python
client speaks dicts over PostgREST, so a heavier ORM would just add a
translation layer without adding safety. This class exists to give the
rest of the codebase typed attribute access and a couple of small
convenience methods instead of passing raw dicts everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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
            last_used_at=row.get("last_used_at"),
            usage_count=row.get("usage_count", 0),
            next_global_review=row.get("next_global_review"),
            selection_weight=row.get("selection_weight", 1.0),
            quality_score=row.get("quality_score", 1.0),
        )
