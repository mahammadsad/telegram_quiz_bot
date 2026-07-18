from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as api_module
from services import personal_learning_service as service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718181849_personalized_learning_foundation.sql"
FK_MIGRATION = ROOT / "supabase" / "migrations" / "20260718183203_personalized_learning_fk_compatibility.sql"
client = TestClient(api_module.app)


def test_personalized_learning_migration_is_private_atomic_and_answer_free():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "exam_catalogue",
        "user_preferences",
        "user_question_bookmarks",
        "user_resource_bookmarks",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "sync_personal_review_schedule_after_answer" in sql
    assert "after insert on public.quiz_attempt_answers" in sql
    assert "when new.is_correct is not true then 1" in sql
    assert "when v_slow_or_uncertain then 3" in sql
    assert "when public.personal_review_schedule.repetition_count = 1 then 14" in sql
    assert "when public.personal_review_schedule.repetition_count = 2 then 30" in sql
    assert "else 60" in sql
    for function in (
        "get_user_due_reviews",
        "get_user_wrong_questions",
        "get_user_learning_dashboard",
        "get_user_bookmarks",
        "set_user_bookmark",
        "get_user_preferences",
        "save_user_preferences",
    ):
        assert f"function public.{function}" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "security definer" not in sql
    due_rpc = sql.split("function public.get_user_due_reviews", 1)[1].split(
        "function public.get_user_wrong_questions", 1
    )[0]
    wrong_rpc = sql.split("function public.get_user_wrong_questions", 1)[1].split(
        "function public.get_user_learning_dashboard", 1
    )[0]
    assert "correct_option" not in due_rpc
    assert "correct_option" not in wrong_rpc


def test_legacy_review_foreign_keys_are_forward_fixed_to_cascade():
    sql = FK_MIGRATION.read_text(encoding="utf-8").lower()
    assert "personal_review_schedule_user_id_fkey" in sql
    assert "personal_review_schedule_question_id_fkey" in sql
    assert sql.count("on delete cascade") == 2


def test_dashboard_endpoint_requires_telegram_header(monkeypatch):
    monkeypatch.setattr(api_module, "DEV_ALLOW_UNVERIFIED_TELEGRAM", False)
    assert client.get("/api/me/dashboard").status_code == 401
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "dashboard",
        lambda user: {"todayAnswered": 10, "dueReviews": 2},
    )
    response = client.get(
        "/api/me/dashboard",
        headers={"X-Telegram-Init-Data": "signed"},
    )
    assert response.status_code == 200
    assert response.json() == {"todayAnswered": 10, "dueReviews": 2}


def test_private_learning_endpoints_project_authenticated_user(monkeypatch):
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "due_reviews",
        lambda user, limit, offset: {"total": 1, "rows": [{"questionId": "q1"}]},
    )
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "wrong_questions",
        lambda user, subject_key, limit, offset: {"total": 2, "rows": []},
    )
    headers = {"X-Telegram-Init-Data": "signed"}
    assert client.get("/api/me/reviews/due", headers=headers).json()["total"] == 1
    assert client.get(
        "/api/me/wrong-questions?subject=computer", headers=headers
    ).json()["total"] == 2


def test_bookmark_and_preference_contracts(monkeypatch):
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    bookmark = {}
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "set_bookmark",
        lambda user, **kwargs: bookmark.update(kwargs) or {"active": kwargs["active"]},
    )
    response = client.post(
        "/api/me/bookmarks",
        json={
            "initData": "signed",
            "itemType": "question",
            "itemId": "22222222-2222-4222-8222-222222222222",
            "active": True,
        },
    )
    assert response.status_code == 200
    assert bookmark["item_type"] == "question"

    captured = {}
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "save_preferences",
        lambda user, payload: captured.update(payload) or {"dailyQuestionTarget": 30},
    )
    response = client.put(
        "/api/me/preferences",
        json={
            "initData": "signed",
            "targetExams": ["SSC"],
            "preferredSubjects": ["mathematics", "reasoning"],
            "dailyQuestionTarget": 30,
            "preferredLanguage": "bn",
            "difficultyPreference": "adaptive",
            "quizMode": "timed",
            "leaderboardVisible": False,
        },
    )
    assert response.status_code == 200
    assert captured["preferred_subjects"] == ["mathematics", "reasoning"]
    assert captured["leaderboard_visible"] is False


def test_service_validates_preferences_and_never_exposes_private_fields(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    saved = {}
    monkeypatch.setattr(
        service.personal_learning_repo,
        "save_preferences",
        lambda user_id, payload: saved.update(payload) or {"dailyQuestionTarget": 20},
    )
    payload = {
        "target_exams": ["SSC", "RAILWAY", "SSC"],
        "preferred_subjects": ["mathematics", "reasoning"],
        "daily_question_target": 20,
        "preferred_language": "bn",
        "difficulty_preference": "adaptive",
        "quiz_mode": "practice",
        "leaderboard_visible": True,
        "public_display_name": "পরীক্ষার্থী",
        "username_visible": False,
        "daily_reminder_enabled": False,
    }
    assert service.save_preferences({"id": 123}, payload)["dailyQuestionTarget"] == 20
    assert saved["target_exams"] == ["SSC", "RAILWAY"]
    with pytest.raises(ValueError, match="Unknown target exam"):
        service.save_preferences({"id": 123}, {**payload, "target_exams": ["FAKE"]})
    with pytest.raises(ValueError, match="private field"):
        service._safe({"telegram_id": 123})
