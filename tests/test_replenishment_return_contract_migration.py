from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260830095800_return_new_replenishment_jobs.sql"
)


def test_replenishment_return_wrapper_retries_only_an_empty_first_read() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "rename to ensure_due_content_replenishment_jobs_source_optional_base" in sql
    assert sql.count(
        "public.ensure_due_content_replenishment_jobs_source_optional_base(p_now)"
    ) == 2
    assert "if not found then" in sql
    assert "security invoker" in sql
    assert "set search_path = ''" in sql


def test_replenishment_return_wrapper_keeps_both_functions_private() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    for signature in (
        "public.ensure_due_content_replenishment_jobs_source_optional_base(timestamptz)",
        "public.ensure_due_content_replenishment_jobs(timestamptz)",
    ):
        assert f"revoke all on function {signature}" in " ".join(sql.split())
        assert f"grant execute on function {signature}" in " ".join(sql.split())
    for destructive in ("delete from", "truncate ", "drop table", "drop schema"):
        assert destructive not in sql
