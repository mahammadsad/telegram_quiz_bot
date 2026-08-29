from pathlib import Path

from storage import quiz_jobs_repo

MIGRATION = (
    Path(__file__).parents[1]
    / "supabase/migrations/20260829163136_guarded_validation_dead_letter_recovery.sql"
).read_text(encoding="utf-8")


def test_validation_dead_letter_recovery_is_guarded_audited_and_service_only():
    lowered = MIGRATION.lower()
    assert "v_job.status <> 'dead_letter'" in lowered
    assert "v_job.last_error_category <> 'validation_failed'" in lowered
    assert "v_job.retry_count is distinct from p_expected_retry_count" in lowered
    assert "v_run.question_count <> 0" in lowered
    assert "v_run.content_checksum is not null" in lowered
    assert "from public.quiz_questions mapped" in lowered
    assert "chapter.active" in lowered
    assert "chapter.rotation_enabled" in lowered
    assert "'operator_validation_requeued'" in lowered
    assert "retry_count =" not in lowered
    assert (
        "revoke all on function public.requeue_validation_dead_letter(\n"
        "    uuid,text,text,text,integer,text,text,text\n"
        ") from public, anon, authenticated"
    ) in lowered
    assert (
        "grant execute on function public.requeue_validation_dead_letter(\n"
        "    uuid,text,text,text,integer,text,text,text\n"
        ") to service_role"
    ) in lowered


def test_validation_dead_letter_repository_calls_exact_rpc(monkeypatch):
    captured = {}

    class Query:
        def execute(self):
            return type("Response", (), {"data": {"status": "retry_wait"}})()

    class Client:
        def rpc(self, name, payload):
            captured.update(name=name, payload=payload)
            return Query()

    monkeypatch.setattr(quiz_jobs_repo, "get_client", Client)
    result = quiz_jobs_repo.requeue_validation_dead_letter(
        job_id="11111111-1111-4111-8111-111111111111",
        actor="release-operator",
        reason="Retry rotation passed CI and deployed smoke.",
        expected_error_code="QuizValidationError",
        expected_retry_count=8,
        expected_chapter="ত্রিকোণমিতি",
        replacement_chapter="জ্যামিতি",
        release_sha="a" * 40,
    )

    assert result == {"status": "retry_wait"}
    assert captured == {
        "name": "requeue_validation_dead_letter",
        "payload": {
            "p_job_id": "11111111-1111-4111-8111-111111111111",
            "p_actor": "release-operator",
            "p_reason": "Retry rotation passed CI and deployed smoke.",
            "p_expected_error_code": "QuizValidationError",
            "p_expected_retry_count": 8,
            "p_expected_chapter": "ত্রিকোণমিতি",
            "p_replacement_chapter": "জ্যামিতি",
            "p_release_sha": "a" * 40,
        },
    }
