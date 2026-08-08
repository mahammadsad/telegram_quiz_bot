from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from storage import quiz_runs_repo

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808063007_atomic_quiz_post_finalization.sql"
)


def test_post_finalization_migration_is_atomic_idempotent_and_locked_down():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    finalize = sql.split("function public.finalize_quiz_post", 1)[1]
    assert "for update" in finalize
    assert "status = 'posted'" in finalize
    assert "idempotent_replay" in finalize
    assert "usage_count = question.usage_count + 1" in finalize
    assert "update public.quiz_micro_topics" in finalize
    assert "update public.source_documents" in finalize
    assert "update public.quiz_chapters" in finalize
    assert "insert into public.chapter_history" in finalize
    assert "posting intent was not persisted before delivery" in finalize
    assert "revoke all on function public.finalize_quiz_post" in sql
    assert ") from public, anon, authenticated;" in sql
    assert ") to service_role;" in sql
    assert "security definer" in finalize
    assert "set search_path = ''" in finalize


def test_post_finalization_contract_is_required_and_self_describing():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "function public.get_post_finalization_contract" in sql
    assert "20260808063007" in sql
    assert "function_permission_failures" in sql
    assert "missing_columns" in sql


def test_finalize_repository_passes_ack_and_not_stale_counters(monkeypatch):
    calls = []

    class Result:
        data = {"quiz_id": "20260808-history", "status": "posted"}

    class Client:
        def rpc(self, name, params):
            calls.append((name, params))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(quiz_runs_repo, "get_client", Client)
    result = quiz_runs_repo.finalize_post(
        quiz_id="20260808-history",
        worker_id="worker-1",
        telegram_message_id=123,
        acknowledged_at=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
        telegram_chat_id=-100,
        telegram_thread_id=17,
        min_gap_days=21,
        max_gap_days=180,
    )

    assert result["status"] == "posted"
    assert calls[0][0] == "finalize_quiz_post"
    assert "usage_count" not in calls[0][1]
    assert calls[0][1]["p_telegram_message_id"] == 123
