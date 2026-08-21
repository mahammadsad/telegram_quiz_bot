from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260820090000_server_timed_daily_attempts.sql"


def test_daily_attempt_timing_migration_ignores_client_clock_for_rank() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    wrapper = sql.split("create or replace function public.submit_server_timed_quiz_attempt_atomic", 1)[1]
    assert "clock_timestamp() - v_start.started_at" in wrapper
    assert "public.submit_quiz_attempt_atomic(" in wrapper
    assert "p_client_duration_seconds" in wrapper
    assert "p_answers,\n        v_duration,\n        null," in wrapper
    assert "legacy_without_server_start" in wrapper
    assert "timingTrusted" in wrapper


def test_start_lifecycle_is_idempotent_and_detects_parallel_devices() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "unique (quiz_id, user_id, client_attempt_id)" in sql
    assert "on conflict (quiz_id, user_id, client_attempt_id) do nothing" in sql
    assert "multi_device_or_parallel_start" in sql
    assert "client_clock_mismatch" in sql
    assert "attempt_deadline_exceeded" in sql
