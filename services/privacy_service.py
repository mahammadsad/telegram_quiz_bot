"""Freshly authenticated learner privacy rights."""

from __future__ import annotations

from models.user import User
from storage import privacy_repo, users_repo


def export_my_data(telegram_user: dict) -> dict:
    return privacy_repo.export(_user_id(telegram_user))


def request_delete_my_account(telegram_user: dict) -> dict:
    return privacy_repo.request_deletion(_user_id(telegram_user))


def cancel_delete_my_account(telegram_user: dict) -> dict:
    return privacy_repo.cancel_deletion(_user_id(telegram_user))


def _user_id(telegram_user: dict) -> str:
    return str(users_repo.upsert_user(User.from_telegram(telegram_user))["id"])
