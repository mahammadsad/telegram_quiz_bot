from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app as api_module
from services import leaderboard_privacy

client = TestClient(api_module.app)
QUIZ_ID = "20260710-history"
PRIVATE_KEYS = {
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


def _all_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key
            for item in value.values()
            for key in _all_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def _assert_no_store(response) -> None:
    assert response.headers["cache-control"] == (
        "no-store, private, max-age=0, must-revalidate"
    )
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert response.headers["surrogate-control"] == "no-store"
    vary = {
        item.strip().casefold()
        for item in response.headers["vary"].split(",")
    }
    assert "x-telegram-init-data" in vary


def _typed_payload() -> dict[str, Any]:
    return {
        "type": "weekly_accuracy",
        "participants": 3,
        "limit": 20,
        "offset": 0,
        "rows": [
            {
                "rank": 1,
                "displayName": "Private Telegram Name",
                "value": 92,
                "first_name": "Private",
                "lastName": "Telegram Name",
                "username": "private_handle",
                "profilePhotoUrl": "https://example.invalid/private.jpg",
                "nested": {"token": "private-token"},
            },
            {
                "rank": 2,
                "displayName": "স্বেচ্ছায় দেওয়া নাম",
                "identitySource": "public_display_name",
                "value": 88,
            },
            {
                "rank": 3,
                "displayName": "@chosen_user",
                "identitySource": "public_username",
                "value": 84,
                "isCurrentUser": True,
            },
        ],
        "currentUser": {
            "rank": 3,
            "displayName": "@chosen_user",
            "identitySource": "public_username",
            "value": 84,
            "isCurrentUser": True,
            "userId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        },
        "telegramId": 123456789,
        "initData": "signed-private-data",
    }


def _quiz_payload() -> dict[str, Any]:
    return {
        "quizId": QUIZ_ID,
        "participants": 2,
        "limit": 10,
        "offset": 0,
        "rows": [
            {
                "rank": 1,
                "displayName": "শিক্ষার্থী 0123456789AB",
                "identitySource": "anonymous",
                "score": 10,
                "netScore": 10,
                "total": 10,
                "firstName": "Private",
                "photo_url": "https://example.invalid/private.jpg",
            },
            {
                "rank": 2,
                "displayName": "<img src=x onerror=alert(1)>",
                "identitySource": "public_display_name",
                "score": 9,
                "netScore": 8.75,
                "negativeMarks": 0.25,
                "total": 10,
            },
        ],
        "currentUser": {
            "rank": 2,
            "displayName": "<img src=x onerror=alert(1)>",
            "identitySource": "public_display_name",
            "score": 9,
            "netScore": 8.75,
            "isCurrentUser": True,
            "profilePhotoUrl": "https://example.invalid/private.jpg",
        },
        "markingScheme": {
            "rightMarks": 1,
            "wrongPenalty": 0.25,
            "blankMarks": 0,
            "negativeMarking": True,
            "token": "not-public",
        },
    }


def test_typed_projection_requires_trusted_identity_source_and_strips_private_data():
    projected = leaderboard_privacy.project_typed_leaderboard(_typed_payload())

    assert projected["rows"][0]["displayName"] == "গোপন শিক্ষার্থী"
    assert projected["rows"][0]["initials"] == "শি"
    assert projected["rows"][1]["displayName"] == "স্বেচ্ছায় দেওয়া নাম"
    assert projected["rows"][2]["displayName"] == "@chosen_user"
    assert projected["currentUser"]["rank"] == 3
    assert not (_all_keys(projected) & PRIVATE_KEYS)


def test_quiz_projection_keeps_scores_but_never_photos_or_internal_markers():
    projected = leaderboard_privacy.project_quiz_leaderboard(_quiz_payload())

    assert projected["rows"][0]["displayName"] == "শিক্ষার্থী 0123456789AB"
    assert projected["rows"][0]["initials"] == "শি"
    assert projected["rows"][1]["netScore"] == 8.75
    assert projected["rows"][1]["displayName"] == "<img src=x onerror=alert(1)>"
    assert projected["currentUser"]["isCurrentUser"] is True
    assert projected["markingScheme"]["wrongPenalty"] == 0.25
    assert not (_all_keys(projected) & PRIVATE_KEYS)


@pytest.mark.parametrize(
    "path,kind",
    [
        ("/api/leaderboard?limit=20&offset=0", "typed"),
        ("/api/leaderboards/weekly_accuracy?limit=20&offset=0", "typed"),
        (f"/api/quiz/{QUIZ_ID}/leaderboard?limit=10&offset=0", "quiz"),
    ],
)
def test_all_public_leaderboard_routes_are_allowlisted_and_no_store(
    monkeypatch,
    path: str,
    kind: str,
):
    monkeypatch.setattr(
        api_module.stats_repo,
        "typed_leaderboard_for_user",
        lambda *args, **kwargs: _typed_payload(),
    )
    monkeypatch.setattr(
        api_module.stats_repo,
        "quiz_leaderboard_for_user",
        lambda *args, **kwargs: _quiz_payload(),
    )

    response = client.get(path)

    assert response.status_code == 200
    _assert_no_store(response)
    assert not (_all_keys(response.json()) & PRIVATE_KEYS)
    if kind == "typed":
        assert response.json()["rows"][0]["displayName"] == "গোপন শিক্ষার্থী"
    else:
        assert response.json()["rows"][0]["displayName"].startswith("শিক্ষার্থী ")


def test_authenticated_overall_route_highlights_only_safe_public_identity(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api_module,
        "verify_init_data",
        lambda *args: {"id": 123456, "first_name": "Private"},
    )
    monkeypatch.setattr(
        api_module.users_repo,
        "upsert_user",
        lambda user: {"id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"},
    )

    def leaderboard(*args, **kwargs):
        captured.update(kwargs)
        return _typed_payload()

    monkeypatch.setattr(
        api_module.stats_repo,
        "typed_leaderboard_for_user",
        leaderboard,
    )

    response = client.get(
        "/api/leaderboard?limit=20&offset=0",
        headers={"X-Telegram-Init-Data": "signed"},
    )

    assert response.status_code == 200
    assert captured["user_id"] == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    assert response.json()["currentUser"]["isCurrentUser"] is True
    assert response.json()["currentUser"]["displayName"] == "@chosen_user"
    assert not (_all_keys(response.json()) & PRIVATE_KEYS)
    _assert_no_store(response)


@pytest.mark.parametrize(
    "path",
    [
        "/api/leaderboard",
        "/api/leaderboards/weekly_accuracy",
        f"/api/quiz/{QUIZ_ID}/leaderboard",
    ],
)
def test_leaderboard_errors_are_privacy_safe_and_no_store(monkeypatch, path: str):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private upstream response rejected")

    monkeypatch.setattr(
        api_module.stats_repo,
        "typed_leaderboard_for_user",
        unavailable,
    )
    monkeypatch.setattr(
        api_module.stats_repo,
        "quiz_leaderboard_for_user",
        unavailable,
    )

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {
        "detail": leaderboard_privacy.PRIVACY_MAINTENANCE_MESSAGE
    }
    _assert_no_store(response)


def test_invalid_subject_validation_stays_400_and_no_store():
    response = client.get(
        "/api/leaderboards/subject_accuracy?subject=not-a-subject"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown subject key."
    _assert_no_store(response)


def test_invalid_board_validation_stays_400_and_no_store():
    response = client.get("/api/leaderboards/not-a-board")
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown leaderboard type."
    _assert_no_store(response)


@pytest.mark.parametrize(
    "path,repo_name,expected_limit,expected_offset,payload",
    [
        (
            "/api/leaderboard?limit=500&offset=-4",
            "typed_leaderboard_for_user",
            100,
            0,
            _typed_payload(),
        ),
        (
            "/api/leaderboards/weekly_accuracy?limit=7&offset=9",
            "typed_leaderboard_for_user",
            7,
            9,
            _typed_payload(),
        ),
        (
            f"/api/quiz/{QUIZ_ID}/leaderboard?limit=500&offset=11",
            "quiz_leaderboard_for_user",
            50,
            11,
            _quiz_payload(),
        ),
    ],
)
def test_leaderboard_routes_preserve_bounded_limit_and_offset(
    monkeypatch,
    path: str,
    repo_name: str,
    expected_limit: int,
    expected_offset: int,
    payload: dict[str, Any],
):
    captured = {}

    def repository(*args, **kwargs):
        captured.update(kwargs)
        return payload

    monkeypatch.setattr(api_module.stats_repo, repo_name, repository)

    response = client.get(path)

    assert response.status_code == 200
    assert captured["limit"] == expected_limit
    assert captured["offset"] == expected_offset
    _assert_no_store(response)


def test_vary_merge_preserves_existing_values():
    headers = {"Vary": "Origin, Accept-Encoding"}
    api_module._merge_vary_header(headers, "X-Telegram-Init-Data")
    api_module._merge_vary_header(headers, "x-telegram-init-data")
    assert headers["Vary"] == (
        "Origin, Accept-Encoding, X-Telegram-Init-Data"
    )
