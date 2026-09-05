from __future__ import annotations

from pathlib import Path

from database.contract import CURRENT_AFFAIRS_CHAPTER_GROUNDING_MIGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{CURRENT_AFFAIRS_CHAPTER_GROUNDING_MIGRATION_VERSION}_current_affairs_chapter_grounding.sql"
)


def test_chapter_grounding_filters_before_its_bounded_limit() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    chapter_filter = "chapter.name = p_chapter"
    final_limit = "limit greatest(1, least(coalesce(p_limit, 8), 20))"
    assert chapter_filter in sql
    assert final_limit in sql
    assert sql.index(chapter_filter) < sql.index(final_limit)
    assert "chapter.rotation_enabled" in sql
    assert "source.source_kind in ('official', 'primary')" in sql
    assert "fact.verification_status = 'verified'" in sql


def test_chapter_grounding_advances_fail_closed_contracts() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "current_affairs_generation_coverage_ready" in sql
    assert "currentaffairschaptergrounding" in sql
    assert "security invoker" in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    for destructive in ("delete from", "truncate ", "drop table", "drop schema"):
        assert destructive not in sql
