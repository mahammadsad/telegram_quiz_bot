from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260824052500_fair_content_replenishment_claims.sql"
)


def test_fair_replenishment_claim_is_bounded_round_robin() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "partition by job.subject_key" in sql
    assert "subject_slot" in sql
    assert "last_claimed_at asc nulls first" in sql
    assert "for update of job skip locked" in sql
    assert "least(coalesce(p_limit, 5), 25)" in sql
    assert "security invoker" in sql
