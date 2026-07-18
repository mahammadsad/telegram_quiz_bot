from __future__ import annotations

from pathlib import Path

from storage import quiz_runs_repo

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718015054_atomic_quiz_integrity.sql"


def test_migration_contains_atomic_claim_and_stale_lease_recovery():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "function public.claim_quiz_run" in sql
    assert "claim_expires_at <= now()" in sql
    assert "worker_id = p_worker_id" in sql
    assert "status <> 'posted'" in sql


def test_migration_contains_transactional_pack_and_attempt_functions():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "function public.save_quiz_pack_atomic" in sql
    assert "function public.submit_quiz_attempt_atomic" in sql
    assert "unique (quiz_id, question_order)" in sql
    assert "unique (attempt_id, question_order)" in sql
    assert "pg_advisory_xact_lock" in sql
    submission = sql.split("function public.submit_quiz_attempt_atomic", 1)[1]
    assert submission.index("pg_advisory_xact_lock") < submission.index("select id, answers into")


def test_migration_locks_rpc_and_tables_to_server_role():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "security_invoker = true" in sql
    assert "rls_auto_enable" in sql


def test_claim_repository_passes_logical_worker_and_timeout(monkeypatch):
    calls = []

    class Result:
        data = [{"quiz_id": "20260710-history", "worker_id": "worker-1"}]

    class Client:
        def rpc(self, name, params):
            calls.append((name, params))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(quiz_runs_repo, "get_client", Client)
    claimed = quiz_runs_repo.claim("20260710-history", "worker-1", "generating")
    assert claimed["worker_id"] == "worker-1"
    assert calls[0][0] == "claim_quiz_run"
    assert calls[0][1]["p_quiz_id"] == "20260710-history"
