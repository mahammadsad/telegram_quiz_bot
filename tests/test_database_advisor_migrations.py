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
    schema = (ROOT / "database/schema.sql").read_text(encoding="utf-8")
    migration = (
        ROOT
        / "supabase/migrations/20260821091000_harden_pg_trgm_extension.sql"
    ).read_text(encoding="utf-8")

    assert "create extension if not exists pg_trgm with schema extensions" in schema
    assert "alter extension pg_trgm set schema extensions" in migration
    assert "extensions.similarity" in migration
    assert "drop index if exists public.idx_questions_normalized_text" in migration
