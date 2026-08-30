from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260830095000_source_optional_stable_replenishment.sql"
)


def test_source_optional_replenishment_keeps_current_affairs_gated() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "chapter.rotation_enabled" in sql
    assert "chapter.subject_key <> 'current-affairs'" in sql
    assert "source.verification_status = 'verified'" in sql
    assert "not source.review_required" in sql
    assert "source.expires_at is null or source.expires_at >= p_now" in sql


def test_source_optional_replenishment_is_additive_private_and_bounded() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert ") < 12" in sql
    assert "target_candidate_count, generation_batch_size" in sql
    assert "candidate.micro_topic_id, candidate.due_at, 15, 5" in sql
    assert "on conflict do nothing" in sql
    assert "grant execute on function public.ensure_due_content_replenishment_jobs" in sql
    for destructive in ("delete from", "truncate ", "drop table", "drop schema"):
        assert destructive not in sql
