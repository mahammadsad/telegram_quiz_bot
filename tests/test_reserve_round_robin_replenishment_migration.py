from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260904172137_reserve_tier_round_robin_claims.sql"
)


def test_under_reserve_subjects_receive_a_fair_first_slot() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    priority = sql.index("case when eligible.reserve_gap > 0 then 0 else 1 end")
    subject_round = sql.index("eligible.subject_slot", priority)
    gap_priority = sql.index("eligible.reserve_gap desc", subject_round)

    assert priority < subject_round < gap_priority
    assert "last_claimed_at asc nulls first" in sql


def test_claim_remains_atomic_bounded_non_blocking_and_private() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "for update of job skip locked" in sql
    assert "least(coalesce(p_limit, 5), 25)" in sql
    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_platform_gate_requires_the_round_robin_migration() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "version = '20260904172137'" in sql
    assert "name = 'reserve_tier_round_robin_claims'" in sql
    assert "'reserveroundrobinreplenishment'" in sql
    assert "'contract_version', '1.3.0'" in sql
    assert "'required_migration_version', '20260904172137'" in sql
    assert "get_platform_contract_v1_before_reserve_round_robin" in sql
