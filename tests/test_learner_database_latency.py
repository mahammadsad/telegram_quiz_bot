from __future__ import annotations

from types import SimpleNamespace

import pytest

from database.observability import begin_database_timings, reset_database_timings
from errors import DatabaseIntegrityError
from models.user import User
from storage import personal_learning_repo, users_repo


class FakeRpcClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, payload: dict) -> "FakeRpcClient":
        self.calls.append((name, payload))
        self.current_name = name
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.responses[self.current_name])


def test_user_resolution_uses_the_throttled_rpc_and_safe_timing(monkeypatch) -> None:
    client = FakeRpcClient({"resolve_telegram_user_v2": {"id": "user-1"}})
    monkeypatch.setattr(users_repo, "get_client", lambda: client)
    timings, token = begin_database_timings()
    try:
        row = users_repo.upsert_user(
            User(
                telegram_id=123,
                username="learner",
                first_name="Learner",
                photo_url="https://example.invalid/avatar.jpg",
            )
        )
    finally:
        reset_database_timings(token)

    assert row == {"id": "user-1"}
    assert client.calls == [
        (
            "resolve_telegram_user_v2",
            {
                "p_telegram_id": 123,
                "p_username": "learner",
                "p_first_name": "Learner",
                "p_last_name": None,
                "p_photo_url": "https://example.invalid/avatar.jpg",
                "p_touch_interval_seconds": 900,
            },
        )
    ]
    assert len(timings) == 1
    assert timings[0][0] == "users.resolve"
    assert timings[0][1] >= 0


def test_user_resolution_rejects_an_invalid_rpc_contract(monkeypatch) -> None:
    client = FakeRpcClient({"resolve_telegram_user_v2": []})
    monkeypatch.setattr(users_repo, "get_client", lambda: client)

    with pytest.raises(DatabaseIntegrityError, match="invalid response"):
        users_repo.upsert_user(User(telegram_id=123))


def test_dashboard_and_practice_bootstraps_are_one_rpc_each(monkeypatch) -> None:
    client = FakeRpcClient(
        {
            "get_user_learning_dashboard_bootstrap": {
                "dashboard": {},
                "preferences": {},
            },
            "get_user_practice_bootstrap": {
                "queue": {},
                "preferences": {},
            },
        }
    )
    monkeypatch.setattr(personal_learning_repo, "get_client", lambda: client)

    assert personal_learning_repo.dashboard_bootstrap("user-1")["dashboard"] == {}
    assert personal_learning_repo.practice_bootstrap(
        "user-1",
        source_type="due",
        subject_key=None,
        limit=100,
        offset=0,
    )["queue"] == {}

    assert [name for name, _ in client.calls] == [
        "get_user_learning_dashboard_bootstrap",
        "get_user_practice_bootstrap",
    ]
