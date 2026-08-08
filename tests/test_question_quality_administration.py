from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as api_module
from database.contract import PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION
from services import question_moderation_service, quiz_pack_service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / (PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION + "_phase_e_question_quality_administration.sql")
)
CLIENT = TestClient(api_module.app)
CASE_ID = "11111111-1111-4111-8111-111111111111"
QUESTION_ID = "22222222-2222-4222-8222-222222222222"
REPLACEMENT_ID = "33333333-3333-4333-8333-333333333333"


def test_phase_e4_migration_has_complete_quality_contract() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    for reason in (
        "wrong_answer",
        "multiple_correct",
        "ambiguous",
        "incorrect_explanation",
        "language_spelling",
        "outdated",
        "outside_syllabus",
        "broken_source",
        "duplicate_question",
        "translation_error",
        "other",
    ):
        assert f"'{reason}'" in sql
    for table in (
        "question_reporter_risk_profiles",
        "question_moderation_policies",
        "question_moderation_cases",
        "question_moderation_events",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    for function in (
        "process_question_report_moderation",
        "quarantine_question_authoritatively",
        "review_question_moderation_case",
        "get_question_moderation_queue",
        "get_phase_e_question_quality_contract",
    ):
        assert f"function public.{function}" in sql
    assert "question moderation events are append-only" in sql
    assert "idx_question_moderation_events_superseding" in sql
    assert "correction must use an explicit superseding question version" in sql
    assert "a superseded question cannot be reinstated" in sql
    assert "preserve_historical" in sql
    assert "question_report_burst" in sql
    assert "shared_abuse_cluster" in sql
    assert "reporter_" in sql
    assert "administrator_only" in sql
    assert "drop table" not in sql


def test_new_report_reasons_are_accepted_by_all_api_models() -> None:
    assert {"duplicate_question", "translation_error"} <= quiz_pack_service.REPORT_REASONS
    for reason in ("duplicate_question", "translation_error"):
        quiz = api_module.ReportQuestionRequest.model_validate(
            {
                "quizId": "20260808-history",
                "attemptId": CASE_ID,
                "reason": reason,
            }
        )
        practice = api_module.PracticeQuestionReportRequest.model_validate({"attemptId": CASE_ID, "reason": reason})
        assert quiz.reason == reason
        assert practice.reason == reason


def test_moderation_service_validates_version_and_authoritative_policy(monkeypatch) -> None:
    monkeypatch.setattr(question_moderation_service, "is_admin", lambda user: True)
    captured: dict = {}
    monkeypatch.setattr(
        question_moderation_service.question_moderation_repo,
        "quarantine_question",
        lambda question_id, **kwargs: captured.update(question_id=question_id, **kwargs) or {"status": "quarantined"},
    )
    result = question_moderation_service.authoritative_quarantine(
        {"id": 99},
        question_id=QUESTION_ID,
        trigger="authoritative_correction",
        reason="Official answer key correction",
        superseding_question_id=REPLACEMENT_ID,
    )
    assert result["status"] == "quarantined"
    assert captured["superseding_question_id"] == REPLACEMENT_ID
    assert captured["actor"].startswith("telegram-admin:")


def test_moderation_service_rejects_unsafe_decisions(monkeypatch) -> None:
    monkeypatch.setattr(question_moderation_service, "is_admin", lambda user: True)
    for decision, replacement in (
        ("supersede", None),
        ("dismiss", REPLACEMENT_ID),
    ):
        try:
            question_moderation_service.review_case(
                {"id": 99},
                case_id=CASE_ID,
                decision=decision,
                resolution="Reviewed",
                superseding_question_id=replacement,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe review decision was accepted")


def test_protected_admin_queue_and_review_routes(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args, **kwargs: {"id": 99})
    monkeypatch.setattr(
        api_module.question_moderation_service,
        "admin_review_queue",
        lambda user, **kwargs: {"items": [], "total": 0, **kwargs},
    )
    queue = CLIENT.get(
        "/api/admin/questions/reviews?status=quarantined&limit=10&offset=2",
        headers={"X-Telegram-Init-Data": "signed"},
    )
    assert queue.status_code == 200
    assert queue.json()["status"] == "quarantined"

    captured: dict = {}
    monkeypatch.setattr(
        api_module.question_moderation_service,
        "review_case",
        lambda user, **kwargs: captured.update(kwargs) or {"status": "superseded"},
    )
    review = CLIENT.post(
        f"/api/admin/questions/reviews/{CASE_ID}",
        json={
            "initData": "signed",
            "decision": "supersede",
            "resolution": "Official correction reviewed",
            "supersedingQuestionId": REPLACEMENT_ID,
        },
    )
    assert review.status_code == 200
    assert captured["superseding_question_id"] == REPLACEMENT_ID


def test_admin_routes_reject_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args, **kwargs: {"id": 99})
    monkeypatch.setattr(
        api_module.question_moderation_service,
        "admin_review_queue",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("Administrator access required.")),
    )
    response = CLIENT.get(
        "/api/admin/questions/reviews",
        headers={"X-Telegram-Init-Data": "signed"},
    )
    assert response.status_code == 403
