from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as api_module
from database.contract import REQUIRED_MIGRATION_VERSION
from storage.contracts import raise_safe_rate_limit

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260724212939_durable_write_rate_limits.sql"
)
CLIENT = TestClient(api_module.app)
RESOURCE_ID = "11111111-1111-4111-8111-111111111111"
QUESTION_ID = "22222222-2222-4222-8222-222222222222"
ATTEMPT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_forward_migration_durably_protects_every_required_write() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    assert REQUIRED_MIGRATION_VERSION == "20260724212939"
    assert "create table if not exists public.write_rate_limit_buckets" in sql
    assert "alter table public.write_rate_limit_buckets enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "function public.enforce_write_rate_limit" in sql
    assert "updated_at < clock_timestamp() - interval '2 days'" in sql
    for function_name, scope in (
        ("set_user_bookmark", "bookmark"),
        ("save_user_preferences", "preferences"),
        ("submit_resource_feedback", "resource_feedback"),
        ("review_resource_candidate", "resource_review"),
    ):
        body = sql.split(f"function public.{function_name}", 1)[1]
        assert f"'{scope}'" in body.split("end;\n$$;", 1)[0]
        assert "public.enforce_write_rate_limit" in body.split("end;\n$$;", 1)[0]
    assert "required_migration_version = '20260724212939'" in sql
    assert "contract_version = '2.2.0'" not in sql
    assert "drop table" not in sql


@pytest.mark.parametrize(
    "database_message",
    [
        "bookmark rate limit exceeded",
        "preferences rate limit exceeded",
        "quiz submission rate limit exceeded",
        "practice answer rate limit exceeded",
        "resource feedback rate limit exceeded",
        "resource review rate limit exceeded",
    ],
)
def test_repository_error_translation_exposes_only_safe_rate_message(
    database_message: str,
) -> None:
    with pytest.raises(ValueError, match=database_message):
        raise_safe_rate_limit(RuntimeError(f"database detail: {database_message}; hidden context"))


@pytest.mark.parametrize(
    ("target", "method", "path", "payload", "message"),
    [
        (
            "quiz",
            "post",
            "/api/quiz/20260710-history/submit",
            {
                "initData": "signed",
                "answers": [0] * 10,
                "attemptId": ATTEMPT_ID,
            },
            "quiz submission rate limit exceeded",
        ),
        (
            "practice",
            "post",
            f"/api/me/practice/{QUESTION_ID}",
            {
                "initData": "signed",
                "selectedIndex": 1,
                "sourceType": "due",
                "mode": "revision",
                "attemptId": ATTEMPT_ID,
            },
            "practice answer rate limit exceeded",
        ),
        (
            "bookmark",
            "post",
            "/api/me/bookmarks",
            {
                "initData": "signed",
                "itemType": "question",
                "itemId": QUESTION_ID,
                "active": True,
            },
            "bookmark rate limit exceeded",
        ),
        (
            "preferences",
            "put",
            "/api/me/preferences",
            {"initData": "signed"},
            "preferences rate limit exceeded",
        ),
        (
            "feedback",
            "post",
            f"/api/resources/{RESOURCE_ID}/feedback",
            {"initData": "signed", "feedbackType": "low_quality"},
            "resource feedback rate limit exceeded",
        ),
        (
            "review",
            "post",
            f"/api/admin/resources/{RESOURCE_ID}/review",
            {"initData": "signed", "decision": "approve"},
            "resource review rate limit exceeded",
        ),
    ],
)
def test_database_rate_limits_are_http_429(
    monkeypatch,
    target: str,
    method: str,
    path: str,
    payload: dict,
    message: str,
) -> None:
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})

    def reject(*args, **kwargs):
        raise ValueError(message)

    targets = {
        "quiz": (api_module.quiz_pack_service, "submit_quiz_attempts"),
        "practice": (api_module.personal_learning_service, "submit_practice_answer"),
        "bookmark": (api_module.personal_learning_service, "set_bookmark"),
        "preferences": (api_module.personal_learning_service, "save_preferences"),
        "feedback": (api_module.resource_quality_service, "submit_feedback"),
        "review": (api_module.resource_quality_service, "review_candidate"),
    }
    owner, attribute = targets[target]
    monkeypatch.setattr(owner, attribute, reject)

    response = getattr(CLIENT, method)(path, json=payload)

    assert response.status_code == 429
    assert response.json()["detail"] == message
