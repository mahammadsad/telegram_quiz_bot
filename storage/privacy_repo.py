"""Authenticated learner data-rights persistence."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError


def export(user_id: str) -> dict:
    result = get_client().rpc("export_learner_data", {"p_user_id": user_id}).execute()
    if not isinstance(result.data, dict) or "profile" not in result.data:
        raise DatabaseIntegrityError("Learner data export returned an invalid response.")
    return result.data


def request_deletion(user_id: str) -> dict:
    result = get_client().rpc("request_account_deletion", {"p_user_id": user_id}).execute()
    if not isinstance(result.data, dict) or "requestId" not in result.data:
        raise DatabaseIntegrityError("Account deletion request returned an invalid response.")
    return result.data


def cancel_deletion(user_id: str) -> dict:
    result = get_client().rpc("cancel_account_deletion", {"p_user_id": user_id}).execute()
    if not isinstance(result.data, dict) or "cancelled" not in result.data:
        raise DatabaseIntegrityError("Account deletion cancellation returned an invalid response.")
    return result.data
