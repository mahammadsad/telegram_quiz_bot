from pathlib import Path

SQL = (
    Path(__file__).parents[1]
    / "supabase/migrations/20260808071500_durable_quiz_jobs.sql"
).read_text()


def test_durable_job_contract_has_claims_leases_events_and_reconciliation():
    required = (
        "create table if not exists public.quiz_jobs",
        "create table if not exists public.quiz_job_events",
        "for update skip locked",
        "posting_unknown",
        "dead_letter",
        "claim_due_quiz_jobs",
        "fail_quiz_job",
        "reconcile_quiz_job_unknown",
        "reflect_quiz_run_delivery_on_job",
    )
    lowered = SQL.lower()
    for fragment in required:
        assert fragment in lowered


def test_durable_job_contract_is_service_role_only_and_events_are_append_only():
    lowered = SQL.lower()
    assert "enable row level security" in lowered
    assert "revoke all on table public.quiz_jobs from public, anon, authenticated" in lowered
    assert "grant select, insert, update on table public.quiz_jobs to service_role" in lowered
    assert "quiz_job_events is append-only" in lowered
