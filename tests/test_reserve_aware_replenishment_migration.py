from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260904164836_reserve_aware_replenishment_claims.sql"
)


def test_claim_priority_matches_the_configured_safe_reserve() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    production = tomllib.loads(
        (ROOT / "config" / "production.toml").read_text(encoding="utf-8")
    )
    target = int(production["content_inventory"]["target_days"]) * 10

    assert "verified_subject_capacity as materialized" in sql
    assert f"{target} - coalesce(capacity.verified_count, 0)" in sql
    assert "eligible.reserve_gap desc" in sql
    assert "eligible.subject_slot" in sql
    assert "last_claimed_at asc nulls first" in sql


def test_claim_capacity_keeps_the_fail_closed_inventory_contract() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    required_fragments = (
        "question.status = 'active'",
        "question.verification_status = 'verified'",
        "question.inventory_status in ('verified', 'used')",
        "not question.review_required",
        "question.knowledge_point_id is not null",
        "question.variant_fingerprint is not null",
        "source.verification_status = 'verified'",
        "not source.review_required",
        "evidence.support_type = 'supports'",
        "fact.verification_status = 'verified'",
        "not fact.review_required",
    )
    for fragment in required_fragments:
        assert fragment in sql


def test_claim_remains_atomic_bounded_non_blocking_and_private() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "for update of job skip locked" in sql
    assert "least(coalesce(p_limit, 5), 25)" in sql
    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert "revoke all on function public.claim_content_replenishment_jobs" in sql
    assert "from public, anon, authenticated" in sql
    assert "grant execute on function public.claim_content_replenishment_jobs" in sql
    assert "to service_role" in sql


def test_platform_gate_accepts_exact_or_hosted_logical_migration_identity() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "version = '20260904164836'" in sql
    assert "name = 'reserve_aware_replenishment_claims'" in sql
    assert "'reserveawarereplenishment'" in sql
    assert "'contract_version', '1.2.0'" in sql
    assert "'required_migration_version', '20260904164836'" in sql
    assert "security definer" in sql
    assert "get_platform_contract_v1_before_reserve_priority" in sql
