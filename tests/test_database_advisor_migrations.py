from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_job_subject_foreign_keys_have_covering_indexes() -> None:
    migration = (
        ROOT
        / "supabase/migrations/20260821090000_job_subject_fk_indexes.sql"
    ).read_text(encoding="utf-8")

    assert "idx_quiz_jobs_subject_key" in migration
    assert "public.quiz_jobs (subject_key)" in migration
    assert "idx_content_replenishment_jobs_subject_key" in migration
    assert "public.content_replenishment_jobs (subject_key)" in migration


def test_pg_trgm_is_kept_out_of_the_public_schema() -> None:
    migration = (
        ROOT
        / "supabase/migrations/20260821091000_harden_pg_trgm_extension.sql"
    ).read_text(encoding="utf-8")

    assert "alter extension pg_trgm set schema extensions" in migration
    assert "extensions.similarity" in migration
    assert "drop index if exists public.idx_questions_normalized_text" in migration


def test_post_finalization_requires_chapter_history_uniqueness() -> None:
    migration = (
        ROOT
        / "supabase/migrations/20260821100000_restore_chapter_history_uniqueness.sql"
    ).read_text(encoding="utf-8")

    assert "unique (subject_key, selected_for)" in migration
    assert "chapter_history_uniqueness_ready" in migration
    assert "'post_finalization_migration_version', '20260821100000'" in migration
