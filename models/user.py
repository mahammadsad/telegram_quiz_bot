"""User domain model — mirrors the `users` table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    photo_url: Optional[str] = None
    id: Optional[str] = None
    join_date: Optional[str] = None
    last_active: Optional[str] = None

    @classmethod
    def from_telegram(cls, telegram_user: dict) -> "User":
        """Build from Telegram's `User` object as seen in a poll_answer update."""
        return cls(
            telegram_id=telegram_user["id"],
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            last_name=telegram_user.get("last_name"),
            photo_url=(
                telegram_user.get("photo_url")
                if str(telegram_user.get("photo_url") or "").startswith("https://")
                else None
            ),
        )

    @classmethod
    def from_row(cls, row: dict) -> "User":
        return cls(
            id=row.get("id"),
            telegram_id=row["telegram_id"],
            username=row.get("username"),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            photo_url=row.get("photo_url"),
            join_date=row.get("join_date"),
            last_active=row.get("last_active"),
        )
