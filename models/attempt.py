"""User attempt domain model — mirrors the `user_attempts` table.

This is the raw-event table: no calculated fields (accuracy, score, rank)
ever live here or anywhere else. See database/schema.sql's views
(v_user_stats, v_question_stats) for how those are computed on demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Attempt:
    user_id: str
    question_id: str
    selected_option: str          # 'A' | 'B' | 'C' | 'D'
    is_correct: bool
    poll_id: Optional[str] = None
    response_time_seconds: Optional[float] = None
    session_type: str = "daily_mcq"
    id: Optional[str] = None
    answered_at: Optional[str] = None

    def to_insert_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "question_id": self.question_id,
            "poll_id": self.poll_id,
            "selected_option": self.selected_option,
            "is_correct": self.is_correct,
            "response_time_seconds": self.response_time_seconds,
            "session_type": self.session_type,
        }
