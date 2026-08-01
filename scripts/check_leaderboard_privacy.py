"""Sanitized live privacy smoke check for public leaderboard responses.

The command keeps database identities and API payloads in memory and prints
aggregate counters only. It is safe for CI/operator logs when configured with
the target environment's existing service-role credential.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BOARD_TYPES = (
    "overall_rank",
    "daily_accuracy",
    "weekly_accuracy",
    "monthly_accuracy",
    "subject_accuracy",
    "improvement",
    "consistency",
    "revision_completion",
)
RAW_IDENTIFIER_KEYS = {
    "telegram_id",
    "telegramId",
    "user_id",
    "userId",
    "first_name",
    "firstName",
    "last_name",
    "lastName",
    "username",
    "photo_url",
    "profilePhotoUrl",
    "email",
    "phone",
    "initData",
    "token",
    "identitySource",
    "identity_source",
}


class PrivacySmokeError(RuntimeError):
    """A deliberately detail-free smoke-check failure."""


@dataclass(frozen=True, slots=True)
class PrivacyCounts:
    private_name_matches: int = 0
    private_username_matches: int = 0
    private_photo_matches: int = 0
    raw_identifier_fields: int = 0


def _normalized_strings(values: Iterable[object]) -> set[str]:
    return {
        value.strip().casefold()
        for value in values
        if isinstance(value, str) and value.strip()
    }


def _identity_sets(users: list[Mapping[str, Any]]) -> tuple[set[str], ...]:
    public_names = _normalized_strings(
        user.get("public_display_name") for user in users
    )
    public_usernames = _normalized_strings(
        f"@{str(user.get('username')).strip()}"
        for user in users
        if user.get("username_visible") is True and user.get("username")
    )
    private_names: set[str] = set()
    private_usernames: set[str] = set()
    private_photos: set[str] = set()
    raw_identifiers: set[str] = set()

    for user in users:
        first = str(user.get("first_name") or "").strip()
        last = str(user.get("last_name") or "").strip()
        private_names.update(_normalized_strings((first, last, f"{first} {last}")))
        username = str(user.get("username") or "").strip()
        if username and user.get("username_visible") is not True:
            private_usernames.update(
                _normalized_strings((username, f"@{username}"))
            )
        private_photos.update(_normalized_strings((user.get("photo_url"),)))
        raw_identifiers.update(
            str(value).strip()
            for value in (user.get("id"), user.get("telegram_id"))
            if value is not None and str(value).strip()
        )

    # An explicitly chosen public label or opted-in @username is allowed even
    # when it happens to equal a stored private value.
    private_names.difference_update(public_names)
    private_usernames.difference_update(public_usernames)
    return private_names, private_usernames, private_photos, raw_identifiers


def audit_payloads(
    users: list[Mapping[str, Any]],
    payloads: Iterable[object],
) -> PrivacyCounts:
    private_names, private_usernames, private_photos, identifiers = (
        _identity_sets(users)
    )
    name_matches = 0
    username_matches = 0
    photo_matches = 0
    raw_fields = 0

    def visit(value: object, *, key: str | None = None) -> None:
        nonlocal name_matches, username_matches, photo_matches, raw_fields
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                if child_key in RAW_IDENTIFIER_KEYS:
                    raw_fields += 1
                visit(child, key=str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                visit(child, key=key)
            return

        normalized = value.strip().casefold() if isinstance(value, str) else ""
        if key in {"displayName", "display_name"}:
            name_matches += normalized in private_names
            username_matches += normalized in private_usernames
        if normalized and normalized in private_photos:
            photo_matches += 1
        if value is not None and not isinstance(value, bool):
            raw_fields += str(value).strip() in identifiers

    for payload in payloads:
        visit(payload)
    return PrivacyCounts(
        private_name_matches=name_matches,
        private_username_matches=username_matches,
        private_photo_matches=photo_matches,
        raw_identifier_fields=raw_fields,
    )


def _request_json(url: str, headers: Mapping[str, str]) -> object:
    try:
        with urlopen(Request(url, headers=dict(headers)), timeout=30) as response:
            return json.load(response)
    except Exception as exc:
        raise PrivacySmokeError("privacy smoke request failed") from exc


def _read_private_users(supabase_url: str, service_key: str) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "select": (
                "id,telegram_id,first_name,last_name,username,photo_url,"
                "public_display_name,username_visible"
            ),
            "limit": "10000",
        }
    )
    payload = _request_json(
        f"{supabase_url.rstrip('/')}/rest/v1/users?{query}",
        {"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise PrivacySmokeError("privacy smoke database response was invalid")
    return payload


def _latest_quiz_id(supabase_url: str, service_key: str) -> str | None:
    query = urlencode(
        {
            "select": "quiz_id",
            "status": "in.(ready,posting,posted,posting_failed)",
            "order": "quiz_date.desc",
            "limit": "1",
        }
    )
    payload = _request_json(
        f"{supabase_url.rstrip('/')}/rest/v1/quiz_runs?{query}",
        {"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )
    if not isinstance(payload, list):
        raise PrivacySmokeError("privacy smoke quiz response was invalid")
    if not payload:
        return None
    quiz_id = payload[0].get("quiz_id") if isinstance(payload[0], dict) else None
    return quiz_id if isinstance(quiz_id, str) and quiz_id else None


def _read_public_payloads(
    app_url: str,
    quiz_id: str | None,
    init_data: str,
) -> list[object]:
    headers = {"X-Telegram-Init-Data": init_data} if init_data else {}
    paths = ["/api/leaderboard?limit=100&offset=0"]
    for board_type in BOARD_TYPES:
        query = {"limit": 100, "offset": 0}
        if board_type == "subject_accuracy":
            query["subject"] = "history"
        paths.append(f"/api/leaderboards/{board_type}?{urlencode(query)}")
    if quiz_id:
        paths.append(
            f"/api/quiz/{quiz_id}/leaderboard?limit=50&offset=0"
        )
    return [
        _request_json(f"{app_url.rstrip('/')}{path}", headers) for path in paths
    ]


def format_counts(counts: PrivacyCounts) -> str:
    return "\n".join(
        (
            f"private_name_matches = {counts.private_name_matches}",
            f"private_username_matches = {counts.private_username_matches}",
            f"private_photo_matches = {counts.private_photo_matches}",
            f"raw_identifier_fields = {counts.raw_identifier_fields}",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default=os.getenv("APP_BASE_URL", ""))
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL", ""))
    args = parser.parse_args()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "")
    init_data = os.getenv("TELEGRAM_INIT_DATA", "")
    if not args.app_url or not args.supabase_url or not service_key:
        print("privacy_smoke_status = configuration_missing")
        return 2
    try:
        users = _read_private_users(args.supabase_url, service_key)
        quiz_id = _latest_quiz_id(args.supabase_url, service_key)
        payloads = _read_public_payloads(args.app_url, quiz_id, init_data)
        counts = audit_payloads(users, payloads)
    except PrivacySmokeError:
        print("privacy_smoke_status = failed")
        return 1
    print(format_counts(counts))
    return 0 if counts == PrivacyCounts() else 1


if __name__ == "__main__":
    sys.exit(main())
