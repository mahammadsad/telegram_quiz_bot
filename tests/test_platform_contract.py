from __future__ import annotations

from pathlib import Path

from database.contract import (
    BOOKMARK_PROJECTION_MIGRATION_VERSION,
    CONTENT_REPLENISHMENT_BACKLOG_MIGRATION_VERSION,
    CURRENT_AFFAIRS_CHAPTER_GROUNDING_MIGRATION_VERSION,
    CURRENT_AFFAIRS_ECONOMY_ROTATION_MIGRATION_VERSION,
    DASHBOARD_TRANSACTION_MIGRATION_VERSION,
    FAIR_CONTENT_REPLENISHMENT_MIGRATION_VERSION,
    LATEST_MIGRATION_VERSION,
    LEARNER_BOOTSTRAP_LATENCY_MIGRATION_VERSION,
    PG_NET_REQUEST_SEQUENCE_MIGRATION_VERSION,
    PG_NET_SCHEMA_HARDENING_MIGRATION_VERSION,
    PLATFORM_CONTRACT_KEY,
    PLATFORM_CONTRACT_MIGRATION_VERSION,
    PLATFORM_CONTRACT_REQUIRED_CHECKS,
    PLATFORM_CONTRACT_VERSION,
    PRIMARY_SCHEDULER_MIGRATION_VERSION,
    REMINDER_DELIVERY_MIGRATION_VERSION,
    REPLENISHMENT_RETURN_CONTRACT_MIGRATION_VERSION,
    RESERVE_AWARE_REPLENISHMENT_MIGRATION_VERSION,
    RESERVE_ROUND_ROBIN_REPLENISHMENT_MIGRATION_VERSION,
    SOURCE_OPTIONAL_REPLENISHMENT_MIGRATION_VERSION,
    VALIDATION_DEAD_LETTER_RECOVERY_MIGRATION_VERSION,
)
from database.platform_contract import failure_reasons, is_ready

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{PLATFORM_CONTRACT_MIGRATION_VERSION}_current_affairs_chapter_grounding.sql"
)
RESERVE_AWARE_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{RESERVE_AWARE_REPLENISHMENT_MIGRATION_VERSION}_reserve_aware_replenishment_claims.sql"
)
LEARNER_BOOTSTRAP_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{LEARNER_BOOTSTRAP_LATENCY_MIGRATION_VERSION}_learner_bootstrap_latency_contract.sql"
)
BASE_MIGRATION = ROOT / "supabase" / "migrations" / "20260822190025_platform_contract_v1.sql"
ROUND_ROBIN_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{RESERVE_ROUND_ROBIN_REPLENISHMENT_MIGRATION_VERSION}_reserve_tier_round_robin_claims.sql"
)
ECONOMY_ROTATION_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{CURRENT_AFFAIRS_ECONOMY_ROTATION_MIGRATION_VERSION}_current_affairs_economy_rotation.sql"
)


def _ready_contract() -> dict:
    return {
        "ready": True,
        "contract_key": PLATFORM_CONTRACT_KEY,
        "contract_version": PLATFORM_CONTRACT_VERSION,
        "required_migration_version": PLATFORM_CONTRACT_MIGRATION_VERSION,
        "migration_applied": True,
        "checks": {name: True for name in PLATFORM_CONTRACT_REQUIRED_CHECKS},
    }


def test_platform_contract_remains_the_scheduler_gate_after_additive_migrations() -> None:
    assert MIGRATION.is_file()
    assert LATEST_MIGRATION_VERSION == CURRENT_AFFAIRS_CHAPTER_GROUNDING_MIGRATION_VERSION
    assert CURRENT_AFFAIRS_ECONOMY_ROTATION_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert RESERVE_ROUND_ROBIN_REPLENISHMENT_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert RESERVE_AWARE_REPLENISHMENT_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert LEARNER_BOOTSTRAP_LATENCY_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert REPLENISHMENT_RETURN_CONTRACT_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert SOURCE_OPTIONAL_REPLENISHMENT_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert VALIDATION_DEAD_LETTER_RECOVERY_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert PG_NET_REQUEST_SEQUENCE_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert PRIMARY_SCHEDULER_MIGRATION_VERSION < DASHBOARD_TRANSACTION_MIGRATION_VERSION
    assert DASHBOARD_TRANSACTION_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert BOOKMARK_PROJECTION_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert PG_NET_SCHEMA_HARDENING_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert CONTENT_REPLENISHMENT_BACKLOG_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert FAIR_CONTENT_REPLENISHMENT_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert REMINDER_DELIVERY_MIGRATION_VERSION < LATEST_MIGRATION_VERSION
    assert PLATFORM_CONTRACT_MIGRATION_VERSION == LATEST_MIGRATION_VERSION

    source = MIGRATION.read_text(encoding="utf-8")
    assert "create function public.get_platform_contract_v1()" in source
    assert "security definer" in source
    assert "set search_path = ''" in source
    assert "revoke all on function public.get_platform_contract_v1()" in source
    assert "grant execute on function public.get_platform_contract_v1() to service_role" in source
    contract_chain = (
        source
        + ECONOMY_ROTATION_MIGRATION.read_text(encoding="utf-8")
        + ROUND_ROBIN_MIGRATION.read_text(encoding="utf-8")
        + RESERVE_AWARE_MIGRATION.read_text(encoding="utf-8")
        + LEARNER_BOOTSTRAP_MIGRATION.read_text(encoding="utf-8")
        + BASE_MIGRATION.read_text(encoding="utf-8")
    )
    assert "generator_provider" in contract_chain
    assert "generator_model" in contract_chain
    assert "supabase_migrations.schema_migrations" in contract_chain
    for check in PLATFORM_CONTRACT_REQUIRED_CHECKS:
        assert f"'{check}'" in contract_chain


def test_platform_contract_validator_accepts_only_exact_complete_contracts() -> None:
    ready = _ready_contract()
    assert is_ready(ready)
    assert failure_reasons(ready) == ()

    missing = _ready_contract()
    missing["checks"]["questionVerificationIndependence"] = False
    assert failure_reasons(missing) == ("questionVerificationIndependence",)

    stale = _ready_contract()
    stale["required_migration_version"] = "20260820100000"
    assert "migration_version" in failure_reasons(stale)
