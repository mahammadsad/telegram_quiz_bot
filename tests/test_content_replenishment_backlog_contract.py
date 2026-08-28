from pathlib import Path

from database.contract import CONTENT_REPLENISHMENT_BACKLOG_MIGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{CONTENT_REPLENISHMENT_BACKLOG_MIGRATION_VERSION}_deduplicate_open_content_replenishment_jobs.sql"
)


def test_replenishment_backlog_migration_preserves_history_and_bounds_open_work() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "delete from public.content_replenishment_jobs" not in sql
    assert "event_type, from_status, to_status" in sql
    assert "'backlog_superseded'" in sql
    assert "'superseded_open_job'" in sql
    assert "idx_content_replenishment_one_open_target" in sql
    assert "nulls not distinct" in sql
    assert "where status in ('due', 'claimed', 'running', 'retry_wait')" in sql
    assert "where not exists" in sql
    assert "on conflict do nothing" in sql
    assert "micro_topic_id is not distinct from p_micro_topic_id" in sql
    assert "v_inserted := found" in sql


def test_replenishment_backlog_contract_is_fail_closed_and_private() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "'replenishment_backlog_migration_version', '20260827040000'" in sql
    assert "'open_job_uniqueness_ready', open_job_uniqueness_ready" in sql
    assert "'duplicate_open_job_count', duplicate_open_job_count" in sql
    assert "duplicate_open_job_count = 0" in sql
    assert "revoke all on function public.ensure_due_content_replenishment_jobs" in sql
    assert "from public, anon, authenticated" in sql
    assert "grant execute on function public.ensure_due_content_replenishment_jobs" in sql
    assert "to service_role" in sql
