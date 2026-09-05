from __future__ import annotations

from pathlib import Path

from config.source_rollout import ROTATION_CHAPTER_KEYS
from database.contract import CURRENT_AFFAIRS_ECONOMY_ROTATION_MIGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{CURRENT_AFFAIRS_ECONOMY_ROTATION_MIGRATION_VERSION}_current_affairs_economy_rotation.sql"
)


def test_economy_rotation_migration_is_forward_only_and_exact() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "current-affairs:economy-reports" in ROTATION_CHAPTER_KEYS["current-affairs"]
    assert "('current-affairs', 3)" in sql
    assert "count(distinct source.id) >= 4" in sql
    assert "count(distinct topic.id) >= 2" in sql
    assert "interval '45 days'" in sql
    assert "source.source_kind in ('official', 'primary')" in sql
    for destructive in ("delete from", "truncate ", "drop table", "drop schema"):
        assert destructive not in sql


def test_economy_rotation_preserves_layered_contracts_and_permissions() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "get_application_schema_contract_v220_source_rollout_before_economy" in sql
    assert "get_application_schema_contract_v220_rate_limits_base" in sql
    assert "get_platform_contract_v1_before_current_affairs_economy" in sql
    assert "current_affairs_economy_rotation_migration_applied" in sql
    assert "currentaffairseconomyrotation" in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
