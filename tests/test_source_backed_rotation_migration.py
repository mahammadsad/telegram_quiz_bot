from __future__ import annotations

import re
from pathlib import Path

from config.source_rollout import ROTATION_CHAPTER_KEYS
from database.contract import (
    REQUIRED_MIGRATION_VERSION,
    SOURCE_ROLLOUT_MIGRATION_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{SOURCE_ROLLOUT_MIGRATION_VERSION}_source_backed_rotation_v1.sql"
)
APPROVED_KEYS = {
    key
    for chapter_keys in ROTATION_CHAPTER_KEYS.values()
    for key in chapter_keys
}


def test_rotation_migration_uses_the_exact_source_approved_allowlist() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    literal_keys = set(re.findall(r"'([a-z][a-z-]+:[a-z0-9-]+)'", sql))

    assert len(APPROVED_KEYS) == 31
    assert literal_keys == APPROVED_KEYS
    assert "update public.quiz_chapters" in sql
    assert "('computer', 7)" in sql
    assert "('current-affairs', 2)" in sql
    assert "source_backed_rotation_ready" in sql
    assert "source_coverage_ready" in sql


def test_rotation_migration_is_forward_only_and_keeps_the_v220_cutover_stable() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    for destructive in (
        "delete from",
        "truncate ",
        "drop table",
        "drop schema",
    ):
        assert destructive not in sql
    assert (
        f"set required_migration_version = '{SOURCE_ROLLOUT_MIGRATION_VERSION}'"
        not in sql
    )
    assert f"'required_migration_version', '{SOURCE_ROLLOUT_MIGRATION_VERSION}'" not in sql
    assert REQUIRED_MIGRATION_VERSION != SOURCE_ROLLOUT_MIGRATION_VERSION
    assert (
        f"'source_rollout_migration_version', '{SOURCE_ROLLOUT_MIGRATION_VERSION}'"
        in sql
    )


def test_rotation_contract_and_grounding_rpc_remain_private_and_ist_aware() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "security definer" in sql
    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert "at time zone 'asia/kolkata'" in sql
    assert (
        "revoke execute on function "
        "public.get_grounding_bundle(text, text, date, integer)"
    ) in sql
    assert (
        "grant execute on function "
        "public.get_grounding_bundle(text, text, date, integer)"
    ) in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
