from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import app as api_module
from services import test_attempts_service as service

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808133000_phase_e_previous_year_and_mock_attempts.sql"
)
CLIENT = TestClient(api_module.app)
INSTANCE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
SECTION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
QUESTION_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")


def test_phase_e3_schema_is_additive_private_and_auditable() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "previous_year_question_provenance",
        "previous_year_question_corrections",
        "test_attempts",
        "test_attempt_section_states",
        "test_attempt_responses",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table}" in sql

    assert "'previous_year_style'" in sql
    assert "generated or style content cannot be verified as an actual pyq" in sql
    assert "correction must use an explicit superseding question version" in sql
    assert "future-dated pyq corrections are not permitted" in sql
    assert "protect_previous_year_corrections_append_only" in sql
    assert "verified pyq provenance is immutable" in sql
    assert "verified pyq answers change only through correction audit" in sql
    assert "after insert on public.previous_year_question_corrections" in sql
    assert "grant select, insert, update on table public.previous_year_question_provenance" not in sql
    assert "('apply_previous_year_correction()')" in sql
    assert "source_checksum" in sql
    assert "license_code" in sql
    assert "reviewer_ref" in sql


def test_phase_e3_attempt_engine_is_atomic_idempotent_and_analytics_ready() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for function in (
        "start_test_attempt_atomic",
        "save_test_attempt_progress_atomic",
        "advance_test_attempt_section_atomic",
        "submit_test_attempt_atomic",
        "auto_submit_due_test_attempts",
        "get_test_attempt_for_user",
    ):
        assert f"function public.{function}" in sql

    assert "unique (test_instance_id, user_id, client_attempt_id)" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "section transition must move to the exact next section" in sql
    assert "marked_for_review" in sql
    assert "mapping.negative_marks_for_wrong" in sql
    assert "'auto_submitted'" in sql
    assert "v_effective_end - started_at" in sql
    assert "first submitted attempt per learner on the same test instance" in sql
    assert "'subjectanalysis'" in sql
    assert "'topicanalysis'" in sql
    assert "'knowledgepointanalysis'" in sql


def test_legacy_attempts_are_mirrored_without_replacing_daily_quiz_contract() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "legacy_quiz_attempt_id uuid unique" in sql
    assert "legacy_quiz_answer_id uuid unique" in sql
    assert "attempt.id," in sql
    assert "answer.id," in sql
    assert "mirror_quiz_attempt_to_shared_test" in sql
    assert "mirror_quiz_answer_to_shared_test" in sql
    assert "legacy_attempts_mirrored" in sql


def test_previous_year_public_projection_is_answer_free() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    projection = sql.split(
        "function public.get_previous_year_question_catalog", 1
    )[1].split(
        "alter table public.previous_year_question_provenance enable row level security",
        1,
    )[0]
    assert "correct_option" not in projection
    assert "'officialanswer'" not in projection
    assert "'correctindex'" not in projection
    assert "question.option_a" in projection
    assert "'humanreviewed', true" in projection


def test_previous_year_service_validates_and_normalizes_filters(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        service.test_attempts_repo,
        "previous_year_catalog",
        lambda **kwargs: captured.update(kwargs) or {"rows": []},
    )
    assert service.previous_year_catalog(
        exam_key=" wbcs ",
        exam_year=2025,
        language=" EN ",
        limit=500,
        offset=-5,
    ) == {"rows": []}
    assert captured == {
        "exam_key": "WBCS",
        "exam_year": 2025,
        "language": "en",
        "limit": 100,
        "offset": 0,
    }

    for kwargs in (
        {"exam_key": "bad key", "exam_year": None, "language": None},
        {"exam_key": None, "exam_year": 1800, "language": None},
        {"exam_key": None, "exam_year": None, "language": "xx"},
    ):
        try:
            service.previous_year_catalog(**kwargs, limit=10, offset=0)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid PYQ filters must fail closed")


def test_test_attempt_api_authentication_and_payload_contracts(monkeypatch) -> None:
    telegram_user = {"id": 12345, "first_name": "Learner"}
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: telegram_user)
    captured: dict = {}
    monkeypatch.setattr(
        api_module.test_attempts_service,
        "start",
        lambda user, **kwargs: captured.update(user=user, **kwargs)
        or {"attemptId": str(ATTEMPT_ID), "status": "in_progress"},
    )

    response = CLIENT.post(
        f"/api/tests/instances/{INSTANCE_ID}/attempts/start",
        json={"initData": "signed", "clientAttemptId": str(ATTEMPT_ID)},
    )
    assert response.status_code == 200
    assert captured == {
        "user": telegram_user,
        "test_instance_id": INSTANCE_ID,
        "client_attempt_id": ATTEMPT_ID,
    }

    monkeypatch.setattr(
        api_module.test_attempts_service,
        "save_progress",
        lambda user, **kwargs: {"attemptId": str(kwargs["attempt_id"]), "saved": True},
    )
    saved = CLIENT.put(
        f"/api/tests/attempts/{ATTEMPT_ID}/progress",
        json={
            "initData": "signed",
            "responses": [{
                "questionId": str(QUESTION_ID),
                "selectedIndex": 2,
                "responseTimeSeconds": 14.5,
                "markedForReview": True,
            }],
        },
    )
    assert saved.status_code == 200
    invalid = CLIENT.put(
        f"/api/tests/attempts/{ATTEMPT_ID}/progress",
        json={
            "initData": "signed",
            "responses": [{"questionId": str(QUESTION_ID), "selectedIndex": True}],
        },
    )
    assert invalid.status_code == 422


def test_test_attempt_owner_read_and_transition_endpoints(monkeypatch) -> None:
    telegram_user = {"id": 54321}
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: telegram_user)
    monkeypatch.setattr(
        api_module.test_attempts_service,
        "advance_section",
        lambda user, **kwargs: {"attemptId": str(kwargs["attempt_id"]), "advanced": True},
    )
    monkeypatch.setattr(
        api_module.test_attempts_service,
        "submit",
        lambda user, **kwargs: {"attemptId": str(kwargs["attempt_id"]), "status": "submitted"},
    )
    monkeypatch.setattr(
        api_module.test_attempts_service,
        "get",
        lambda user, **kwargs: {"attemptId": str(kwargs["attempt_id"]), "status": "submitted"},
    )

    advanced = CLIENT.post(
        f"/api/tests/attempts/{ATTEMPT_ID}/sections/advance",
        json={"initData": "signed", "nextSectionInstanceId": str(SECTION_ID)},
    )
    assert advanced.status_code == 200
    submitted = CLIENT.post(
        f"/api/tests/attempts/{ATTEMPT_ID}/submit",
        json={"initData": "signed", "autoSubmit": False},
    )
    assert submitted.status_code == 200
    recovered = CLIENT.get(
        f"/api/tests/attempts/{ATTEMPT_ID}",
        headers={"X-Telegram-Init-Data": "signed"},
    )
    assert recovered.status_code == 200
    assert recovered.json()["attemptId"] == str(ATTEMPT_ID)


def test_recent_attempts_are_authenticated_bounded_and_answer_free(monkeypatch) -> None:
    telegram_user = {"id": 54321}
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: telegram_user)
    captured: dict = {}
    monkeypatch.setattr(
        api_module.test_attempts_service,
        "recent",
        lambda user, **kwargs: captured.update(user=user, **kwargs)
        or {
            "count": 1,
            "rows": [{
                "attemptId": str(ATTEMPT_ID),
                "testInstanceId": str(INSTANCE_ID),
                "clientAttemptId": str(ATTEMPT_ID),
                "status": "in_progress",
                "answeredCount": 3,
            }],
        },
    )

    response = CLIENT.get(
        "/api/tests/attempts/recent?limit=500",
        headers={"X-Telegram-Init-Data": "signed"},
    )
    assert response.status_code == 200
    assert captured == {"user": telegram_user, "limit": 500}
    assert response.json()["rows"][0]["status"] == "in_progress"
    assert "selectedIndex" not in response.text
    assert "correctOption" not in response.text


def test_recent_attempt_service_projects_only_resumable_or_completed_states(monkeypatch) -> None:
    monkeypatch.setattr(service, "_user_id", lambda user: "user-id")
    captured: dict = {}
    base = {
        "id": str(ATTEMPT_ID),
        "test_instance_id": str(INSTANCE_ID),
        "client_attempt_id": str(ATTEMPT_ID),
        "attempt_number": 1,
        "started_at": "2026-08-24T00:00:00Z",
        "deadline_at": None,
        "submitted_at": None,
        "question_count": 10,
        "answered_count": 3,
        "correct_count": 0,
        "wrong_count": 0,
        "skipped_count": 0,
        "net_marks": "0.00",
    }
    monkeypatch.setattr(
        service.test_attempts_repo,
        "recent",
        lambda user_id, **kwargs: captured.update(user_id=user_id, **kwargs)
        or [{**base, "status": "in_progress"}, {**base, "status": "invalidated"}],
    )

    payload = service.recent({"id": 1}, limit=500)
    assert captured == {"user_id": "user-id", "limit": 100}
    assert payload["count"] == 1
    assert payload["rows"][0]["answeredCount"] == 3


def test_previous_year_endpoint_never_serializes_answer_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module.test_attempts_service,
        "previous_year_catalog",
        lambda **kwargs: {
            "total": 1,
            "rows": [{
                "questionId": str(QUESTION_ID),
                "question": "Question?",
                "options": ["A", "B", "C", "D"],
                "humanReviewed": True,
            }],
        },
    )
    response = CLIENT.get("/api/previous-year?exam=wbcs&year=2025&language=en")
    assert response.status_code == 200
    body = response.text.casefold()
    assert "correctindex" not in body
    assert "officialanswer" not in body
