from pathlib import Path

from storage import quiz_jobs_repo

MIGRATION = (
    Path(__file__).parents[1]
    / "supabase/migrations/20260826080000_operator_blocked_quiz_recovery.sql"
).read_text(encoding="utf-8")


def test_operator_recovery_is_narrow_audited_and_service_only():
    lowered = MIGRATION.lower()
    assert "v_job.status <> 'blocked'" in lowered
    assert "v_job.last_error_code is distinct from btrim(p_expected_error_code)" in lowered
    assert "v_run.status in ('posted', 'posting', 'posting_unknown')" in lowered
    assert "'operator_requeued'" in lowered
    assert "'retry_wait'" in lowered
    assert (
        "revoke all on function public.requeue_blocked_quiz_job(uuid,text,text,text)"
        in lowered
    )
    assert (
        "grant execute on function public.requeue_blocked_quiz_job(uuid,text,text,text)"
        in lowered
    )


def test_operator_recovery_repository_calls_exact_rpc(monkeypatch):
    captured = {}

    class Query:
        def execute(self):
            return type("Response", (), {"data": {"status": "retry_wait"}})()

    class Client:
        def rpc(self, name, payload):
            captured.update(name=name, payload=payload)
            return Query()

    monkeypatch.setattr(quiz_jobs_repo, "get_client", Client)
    result = quiz_jobs_repo.requeue_blocked(
        job_id="11111111-1111-4111-8111-111111111111",
        actor="release-operator",
        reason="Provider request contract was corrected and certified in staging.",
        expected_error_code="GeminiGenerationError",
    )

    assert result == {"status": "retry_wait"}
    assert captured == {
        "name": "requeue_blocked_quiz_job",
        "payload": {
            "p_job_id": "11111111-1111-4111-8111-111111111111",
            "p_actor": "release-operator",
            "p_reason": "Provider request contract was corrected and certified in staging.",
            "p_expected_error_code": "GeminiGenerationError",
        },
    }
