from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as api_module
from services import personal_learning_service as service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718181849_personalized_learning_foundation.sql"
FK_MIGRATION = ROOT / "supabase" / "migrations" / "20260718183203_personalized_learning_fk_compatibility.sql"
UNIQUE_MIGRATION = ROOT / "supabase" / "migrations" / "20260718184505_remove_redundant_personal_review_unique.sql"
ANALYTICS_MIGRATION = ROOT / "supabase" / "migrations" / "20260718185905_learning_analytics_leaderboards.sql"
PRACTICE_MIGRATION = ROOT / "supabase" / "migrations" / "20260718190639_personal_practice_answers.sql"
SUBJECT_PROJECTION_MIGRATION = ROOT / "supabase" / "migrations" / "20260718192154_canonical_subject_learning_projections.sql"
PROJECTION_HOTFIX_MIGRATION = ROOT / "supabase" / "migrations" / "20260729134221_personal_learning_projection_hotfix.sql"
PHASE_E_MIGRATION = ROOT / "supabase" / "migrations" / "20260808113000_phase_e_personal_knowledge_mastery.sql"
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


def test_legacy_review_unique_constraint_is_not_duplicated():
    foundation = MIGRATION.read_text(encoding="utf-8").lower()
    cleanup = UNIQUE_MIGRATION.read_text(encoding="utf-8").lower()
    assert "candidate.contype = 'u'" in cleanup
    assert "drop constraint if exists personal_review_schedule_user_question_key" in cleanup
    assert "from pg_constraint c" in foundation
    assert "array['user_id', 'question_id']::name[]" in foundation


def test_learning_analytics_stay_in_private_paginated_sql_rpcs():
    sql = ANALYTICS_MIGRATION.read_text(encoding="utf-8").lower()
    assert "function public.get_user_learning_dashboard" in sql
    assert "function public.get_leaderboard_page" in sql
    for key in (
        "longeststreak",
        "subjectperformance",
        "chapterperformance",
        "microtopicperformance",
        "difficultyperformance",
        "averageimprovement",
        "revisioncompletion",
        "progressovertime",
    ):
        assert f"'{key}'" in sql
    for board_type in (
        "daily_accuracy",
        "weekly_accuracy",
        "monthly_accuracy",
        "subject_accuracy",
        "improvement",
        "consistency",
        "revision_completion",
    ):
        assert f"'{board_type}'" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "security definer" not in sql


def test_personal_practice_scores_only_after_authenticated_submission():
    sql = PRACTICE_MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.personal_practice_answers" in sql
    assert "function public.submit_personal_practice_answer" in sql
    assert "function public.advance_personal_review_schedule" in sql
    assert "selected option must be between 0 and 3" in sql
    assert "'correctindex'" in sql
    assert "alter table public.personal_practice_answers enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "security definer" not in sql


def test_learner_apis_translate_internal_subject_names_to_canonical_keys():
    sql = SUBJECT_PROJECTION_MIGRATION.read_text(encoding="utf-8").lower()
    assert "function public.canonical_subject_key" in sql
    assert "function public.canonical_subject_internal_name" in sql
    assert "function public.canonicalize_subject_rows" in sql
    for function_name in (
        "get_user_learning_dashboard",
        "get_user_due_reviews",
        "get_user_wrong_questions",
        "get_user_bookmarks",
        "get_leaderboard_page",
    ):
        assert f"function public.{function_name}" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "security definer" not in sql


def test_subject_projection_hotfix_preserves_objects_and_nested_arrays():
    sql = PROJECTION_HOTFIX_MIGRATION.read_text(encoding="utf-8").lower()
    canonicalizer = sql.split(
        "create or replace function public.canonicalize_subject_rows", 1
    )[1].split(
        "alter function public.get_application_schema_contract", 1
    )[0]

    assert "security invoker" in canonicalizer
    assert "jsonb_typeof(p_rows)" in canonicalizer
    assert "jsonb_array_elements(p_rows)" in canonicalizer
    assert "jsonb_each(p_rows)" in canonicalizer
    assert "public.canonicalize_subject_rows(value)" in canonicalizer
    assert "key = 'subjectkey'" in canonicalizer
    assert "'personal_learning_migration_version', '20260729134221'" in sql
    assert "'personal_learning_projection_ready'" in sql
    assert (
        "revoke execute on function public.canonicalize_subject_rows(jsonb)"
        in sql
    )
    assert (
        "grant execute on function public.canonicalize_subject_rows(jsonb)"
        in sql
    )


def test_phase_e_learning_is_knowledge_keyed_private_and_answer_free():
    sql = PHASE_E_MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "personal_knowledge_mastery",
        "personal_knowledge_variant_history",
        "learner_daily_rollups",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "primary key (user_id, knowledge_point_id)" in sql
    assert "unique (source_event_kind, source_event_id)" in sql
    for index in (
        "idx_personal_knowledge_mastery_kp",
        "idx_personal_knowledge_mastery_last_question",
        "idx_personal_knowledge_variant_history_kp",
        "idx_personal_knowledge_variant_history_question",
    ):
        assert f"create index if not exists {index}" in sql
    assert "after insert on public.quiz_attempt_answers" in sql
    assert "after insert on public.personal_practice_answers" in sql
    assert "when p_was_skipped or p_is_correct is false then 1" in sql
    for interval in (3, 7, 14, 30, 60):
        assert f"then {interval}" in sql or f"else {interval}" in sql
    assert "'dueorwrongpercent', 50" in sql
    assert "'weaktopicpercent', 30" in sql
    assert "'broadmaintenancepercent', 20" in sql
    assert "'definition', 'learners with at least one completed official first attempt'" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    review_rpc = sql.split(
        "function public.get_user_knowledge_review_queue", 1
    )[1].split("function public.get_user_learning_daily_rollups", 1)[0]
    assert "correct_option" not in review_rpc
    assert "verification_status = 'verified'" in review_rpc
    assert "inventory_status in ('verified','used')" in review_rpc
    assert "variant_fingerprint is not distinct from due.last_variant_fingerprint" in review_rpc
    assert "function public.get_user_knowledge_mastery_page" in sql
    assert "p_subject_key is null or kp.subject_key = p_subject_key" in sql
    assert "when 'weak' then mastery.mastery_score < 60" in sql
    assert "when 'strong' then mastery.mastery_score >= 80" in sql


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


def test_dashboard_study_plan_prioritizes_due_preferred_subject(monkeypatch) -> None:
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    monkeypatch.setattr(
        service.personal_learning_repo,
        "dashboard",
        lambda user_id: {
            "dailyTarget": 30,
            "todayAnswered": 18,
            "revisionDueToday": 7,
            "weakQuestions": 4,
            "subjectRevisionCounts": [
                {"subjectKey": "history", "due": 5},
                {"subjectKey": "geography", "due": 2},
                {"subjectKey": "science", "due": 9},
            ],
            "subjectPerformance": [
                {"subjectKey": "history", "accuracy": 80},
                {"subjectKey": "geography", "accuracy": 45},
            ],
        },
    )
    monkeypatch.setattr(
        service.personal_learning_repo,
        "preferences",
        lambda user_id: {
            "preferredSubjects": ["history", "geography", "invented"],
            "targetExams": ["WBCS"],
            "dailyQuestionTarget": 30,
        },
    )

    payload = service.dashboard({"id": 123, "first_name": "শিক্ষার্থী"})
    plan = payload["studyPlan"]

    assert plan == {
        "version": 1,
        "personalized": True,
        "preferredSubjects": ["history", "geography"],
        "targetExams": ["WBCS"],
        "dailyQuestionTarget": 30,
        "remainingQuestions": 12,
        "questionTarget": 7,
        "nextAction": "continue_due_revision",
        "subjectKey": "history",
        "examKey": None,
        "reasonCode": "preferred_subject_due",
        "broadcastQuizPersonalized": False,
    }


def test_study_plan_uses_target_exam_only_after_revision_and_weakness() -> None:
    plan = service._study_plan(
        {"todayAnswered": 4, "revisionDueToday": 0, "weakQuestions": 0},
        {
            "preferredSubjects": ["mathematics"],
            "targetExams": ["SSC"],
            "dailyQuestionTarget": 20,
        },
    )

    assert plan["nextAction"] == "target_exam_mock"
    assert plan["examKey"] == "SSC"
    assert plan["remainingQuestions"] == 16
    assert plan["broadcastQuizPersonalized"] is False


def test_study_plan_marks_completed_daily_target_without_over_assignment() -> None:
    plan = service._study_plan(
        {"todayAnswered": 40, "revisionDueToday": 0, "weakQuestions": 0},
        {"preferredSubjects": ["history"], "dailyQuestionTarget": 30},
    )

    assert plan["nextAction"] == "goal_complete"
    assert plan["questionTarget"] == 0


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
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "knowledge_reviews",
        lambda user, limit, offset: {"total": 3, "items": []},
    )
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "daily_rollups",
        lambda user, date_from, date_to, limit, offset: {
            "total": 1,
            "rows": [{"date": "2026-08-08"}],
        },
    )
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "knowledge_mastery",
        lambda user, subject_key, strength, limit, offset: {
            "total": 4,
            "rows": [],
        },
    )
    headers = {"X-Telegram-Init-Data": "signed"}
    assert client.get("/api/me/reviews/due", headers=headers).json()["total"] == 1
    assert client.get(
        "/api/me/wrong-questions?subject=computer", headers=headers
    ).json()["total"] == 2
    assert client.get(
        "/api/me/reviews/knowledge?limit=10&offset=2", headers=headers
    ).json()["total"] == 3
    daily = client.get(
        "/api/me/learning/daily?date_from=2026-08-01&date_to=2026-08-08",
        headers=headers,
    )
    assert daily.status_code == 200
    assert daily.json()["rows"][0]["date"] == "2026-08-08"
    mastery = client.get(
        "/api/me/learning/knowledge-points?subject=history&strength=weak&limit=25",
        headers=headers,
    )
    assert mastery.status_code == 200
    assert mastery.json()["total"] == 4


def test_daily_rollup_service_validates_range_and_serializes_dates(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    captured = {}
    monkeypatch.setattr(
        service.personal_learning_repo,
        "daily_rollups",
        lambda user_id, **kwargs: captured.update(kwargs) or {"rows": []},
    )

    result = service.daily_rollups(
        {"id": 123},
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 8),
        limit=500,
        offset=-4,
    )

    assert result == {"rows": []}
    assert captured == {
        "date_from": "2026-08-01",
        "date_to": "2026-08-08",
        "limit": 100,
        "offset": 0,
    }
    with pytest.raises(ValueError, match="Start date"):
        service.daily_rollups(
            {"id": 123},
            date_from=date(2026, 8, 9),
            date_to=date(2026, 8, 8),
            limit=30,
            offset=0,
        )


def test_knowledge_mastery_service_validates_filters(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    captured = {}
    monkeypatch.setattr(
        service.personal_learning_repo,
        "knowledge_mastery",
        lambda user_id, **kwargs: captured.update(kwargs) or {"rows": []},
    )

    assert service.knowledge_mastery(
        {"id": 123},
        subject_key="history",
        strength="weak",
        limit=500,
        offset=-1,
    ) == {"rows": []}
    assert captured == {
        "subject_key": "history",
        "strength": "weak",
        "limit": 100,
        "offset": 0,
    }
    with pytest.raises(ValueError, match="Unknown subject"):
        service.knowledge_mastery(
            {"id": 123},
            subject_key="invented",
            strength="all",
            limit=20,
            offset=0,
        )
    with pytest.raises(ValueError, match="strength"):
        service.knowledge_mastery(
            {"id": 123},
            subject_key=None,
            strength="invented",
            limit=20,
            offset=0,
        )


def test_practice_answer_requires_auth_and_returns_post_attempt_review(monkeypatch):
    question_id = "22222222-2222-4222-8222-222222222222"
    attempt_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert client.post(
        f"/api/me/practice/{question_id}",
        json={
            "selectedIndex": 1,
            "sourceType": "wrong",
            "mode": "revision",
            "attemptId": attempt_id,
        },
    ).status_code == 401
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    captured = {}
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "submit_practice_answer",
        lambda user, **kwargs: captured.update(kwargs)
        or {"isCorrect": True, "correctIndex": 1, "nextReview": "2026-07-26"},
    )
    response = client.post(
        f"/api/me/practice/{question_id}",
        json={
            "initData": "signed",
            "selectedIndex": 1,
            "sourceType": "due",
            "mode": "revision",
            "attemptId": attempt_id,
            "responseTimeSeconds": 12.5,
            "markedForReview": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["correctIndex"] == 1
    assert captured == {
        "question_id": question_id,
        "client_attempt_id": uuid.UUID(attempt_id),
        "selected_option": 1,
        "source_type": "due",
        "mode": "revision",
        "response_time_seconds": 12.5,
        "marked_for_review": False,
    }


def test_revision_question_report_is_bound_to_the_practice_attempt(monkeypatch):
    question_id = "22222222-2222-4222-8222-222222222222"
    attempt_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    captured = {}
    monkeypatch.setattr(
        api_module.personal_learning_service,
        "report_practice_question",
        lambda user, **kwargs: captured.update(kwargs) or {"status": "accepted"},
    )
    response = client.post(
        f"/api/me/practice/{question_id}/report",
        json={
            "initData": "signed",
            "attemptId": attempt_id,
            "reason": "broken_source",
            "details": "উৎসটি খোলা যাচ্ছে না।",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert captured == {
        "question_id": question_id,
        "client_attempt_id": uuid.UUID(attempt_id),
        "reason": "broken_source",
        "details": "উৎসটি খোলা যাচ্ছে না।",
    }

    invalid = client.post(
        f"/api/me/practice/{question_id}/report",
        json={
            "initData": "signed",
            "attemptId": attempt_id,
            "reason": "invented_reason",
        },
    )
    assert invalid.status_code == 422


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


def test_bookmark_queue_is_explicitly_practice_only(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    monkeypatch.setattr(
        service.personal_learning_repo,
        "bookmarks",
        lambda user_id: {"questions": [], "resources": []},
    )

    payload = service.bookmarks({"id": 123})

    assert payload == {
        "questions": [],
        "resources": [],
        "mode": "practice",
        "sourceType": "bookmark",
    }


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
    with pytest.raises(ValueError, match="not fully supported"):
        service.save_preferences({"id": 123}, {**payload, "preferred_language": "en"})
    with pytest.raises(ValueError, match="not fully supported"):
        service.save_preferences({"id": 123}, {**payload, "preferred_language": "hi"})
    with pytest.raises(ValueError, match="reminders are not available"):
        service.save_preferences({"id": 123}, {**payload, "daily_reminder_enabled": True})
    with pytest.raises(ValueError, match="private field"):
        service._safe({"telegram_id": 123})
