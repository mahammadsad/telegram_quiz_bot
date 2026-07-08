"""Poll domain model — mirrors the `polls` table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Poll:
    telegram_poll_id: str
    telegram_message_id: int
    telegram_chat_id: int
    question_id: str
    session_id: str
    bot_type: str = "daily_mcq"
    run_slot: Optional[str] = None
    id: Optional[str] = None
    posted_at: Optional[str] = None

    def to_insert_dict(self) -> dict:
        return {
            "telegram_poll_id": self.telegram_poll_id,
            "telegram_message_id": self.telegram_message_id,
            "telegram_chat_id": self.telegram_chat_id,
            "question_id": self.question_id,
            "session_id": self.session_id,
            "bot_type": self.bot_type,
            "run_slot": self.run_slot,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Poll":
        return cls(
            id=row.get("id"),
            telegram_poll_id=row["telegram_poll_id"],
            telegram_message_id=row["telegram_message_id"],
            telegram_chat_id=row["telegram_chat_id"],
            question_id=row["question_id"],
            session_id=row["session_id"],
            bot_type=row.get("bot_type", "daily_mcq"),
            run_slot=row.get("run_slot"),
            posted_at=row.get("posted_at"),
        )
