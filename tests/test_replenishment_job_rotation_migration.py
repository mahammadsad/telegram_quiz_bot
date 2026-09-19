from pathlib import Path

from database.contract import REPLENISHMENT_JOB_ROTATION_MIGRATION_VERSION


def test_rotation_preserves_queue_safety_and_uses_durable_claim_history():
    path = Path(__file__).resolve().parents[1] / "supabase/migrations" / (
        f"{REPLENISHMENT_JOB_ROTATION_MIGRATION_VERSION}_durable_replenishment_job_rotation.sql"
    )
    sql = path.read_text().lower()
    assert "claim_recency as materialized" in sql
    assert "where event.event_type = 'claimed'" in sql
    assert "recent.last_claimed_at asc nulls first" in sql
    assert "recent.last_claim_id asc nulls first" in sql
    assert sql.index("recency.last_claim_id asc nulls first") < sql.index("eligible.reserve_gap desc")
    assert "case when eligible.reserve_gap > 0 then 0 else 1 end" in sql
    assert "for update of job skip locked" in sql
    assert "job.lease_expires_at <= p_now" in sql
    assert "coalesce(job.next_retry_at, job.due_at) <= p_now" in sql
    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "retry_count =" not in sql
    assert "delete from" not in sql
