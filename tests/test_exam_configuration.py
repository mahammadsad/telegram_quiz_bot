from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

import app as api_module
from services import exam_config_service as service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808123000_phase_e_exam_configuration.sql"
)
client = TestClient(api_module.app)


def test_exam_migration_is_versioned_additive_private_and_effective_dated() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "exams",
        "exam_stages",
        "exam_papers",
        "exam_sections",
        "exam_syllabus_weights",
        "test_definitions",
        "test_instances",
        "test_section_instances",
        "test_instance_questions",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql

    assert "unique (exam_key, version)" in sql
    assert "unique (exam_id, stage_key, version)" in sql
    assert "unique (exam_stage_id, paper_key, version)" in sql
    assert "unique (exam_paper_id, section_key, version)" in sql
    assert "published exam versions must not overlap" in sql
    assert "published test definition versions must not overlap" in sql
    assert sql.count("effective_from date not null") >= 6
    assert "validate_exam_syllabus_weight_scope" in sql
    assert "knowledge_point_id uuid references public.knowledge_points" in sql
    assert "idx_exam_syllabus_weights_subject" in sql
    assert "idx_test_instance_questions_section_instance" in sql


def test_daily_quick_backfill_preserves_legacy_ids_and_future_sync() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "'daily_quick', 1, 'daily_quick'" in sql
    assert "legacyidspreserved" in sql
    assert "legacy_quiz_id text unique references public.quiz_runs" in sql
    assert "legacy_quiz_question_id uuid unique" in sql
    assert "alter table public.quiz_attempts" in sql
    assert "add column if not exists test_instance_id" in sql
    assert "alter table public.quiz_attempt_answers" in sql
    assert "add column if not exists test_section_instance_id" in sql
    for trigger in (
        "sync_daily_quick_instance",
        "sync_daily_quick_question",
        "attach_test_instance_to_quiz_attempt",
        "attach_test_section_to_quiz_answer",
    ):
        assert trigger in sql
    assert "insert into public.test_instances" in sql
    assert "insert into public.test_instance_questions" in sql
    assert "update public.quiz_attempts attempt" in sql
    assert "update public.quiz_attempt_answers answer" in sql


def test_shared_test_types_and_public_rpc_never_expose_answer_keys() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for test_type in (
        "daily_quick",
        "chapter",
        "subject",
        "mixed",
        "previous_year",
        "sectional_mock",
        "full_mock",
    ):
        assert f"'{test_type}'" in sql
    public_rpc = sql.split(
        "function public.get_public_test_instance", 1
    )[1].split("alter table public.exams enable row level security", 1)[0]
    assert "correct_option" not in public_rpc
    assert "correctoption" not in public_rpc
    assert "question.option_a" in public_rpc
    assert "negative_marks_for_wrong" in public_rpc
    assert "allow_mark_for_review" in public_rpc
    assert "auto_submit" in public_rpc


def test_exam_and_definition_services_validate_filters(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        service.exam_config_repo,
        "exam_catalog",
        lambda **kwargs: captured.update(kwargs) or {"rows": []},
    )
    result = service.exam_catalog(
        as_of=date(2026, 8, 8),
        exam_key=" wbcs ",
        limit=999,
        offset=-5,
    )
    assert result == {"rows": []}
    assert captured == {
        "as_of": "2026-08-08",
        "exam_key": "WBCS",
        "limit": 100,
        "offset": 0,
    }

    try:
        service.test_definition_catalog(
            as_of=None,
            test_type="invented",
            limit=20,
            offset=0,
        )
    except ValueError as exc:
        assert str(exc) == "Unknown test type."
    else:
        raise AssertionError("unknown test types must fail closed")


def test_public_exam_and_test_endpoints_are_answer_free(monkeypatch) -> None:
    test_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr(
        api_module.exam_config_service,
        "exam_catalog",
        lambda **kwargs: {"total": 0, "rows": []},
    )
    monkeypatch.setattr(
        api_module.exam_config_service,
        "test_definition_catalog",
        lambda **kwargs: {
            "total": 1,
            "rows": [{"testType": "daily_quick", "questionCount": 10}],
        },
    )
    monkeypatch.setattr(
        api_module.exam_config_service,
        "public_test_instance",
        lambda value: {
            "testInstanceId": str(value),
            "sections": [
                {
                    "questions": [
                        {
                            "questionId": "q1",
                            "question": "Question?",
                            "options": ["A", "B", "C", "D"],
                        }
                    ]
                }
            ],
        },
    )

    assert client.get("/api/exams").status_code == 200
    definitions = client.get("/api/tests/definitions?test_type=daily_quick")
    assert definitions.status_code == 200
    instance = client.get(f"/api/tests/instances/{test_id}")
    assert instance.status_code == 200
    serialized = instance.text.casefold()
    assert "correctoption" not in serialized
    assert "correct_option" not in serialized


def test_public_test_instance_returns_404_when_unpublished_or_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module.exam_config_service,
        "public_test_instance",
        lambda value: None,
    )
    response = client.get(
        "/api/tests/instances/11111111-1111-4111-8111-111111111111"
    )
    assert response.status_code == 404
