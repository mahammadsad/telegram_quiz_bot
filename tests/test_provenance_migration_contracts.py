from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718112044_question_provenance_reporting.sql"


def test_migration_normalizes_taxonomy_and_provenance():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "quiz_subjects", "quiz_chapters", "quiz_micro_topics",
        "source_documents", "question_verifications", "question_generation_audits",
        "question_reports",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    for field in (
        "source_url", "source_title", "source_domain", "source_published_at",
        "source_accessed_at", "verified_at", "verification_status",
        "verification_notes", "fact_version", "expires_at", "review_required",
    ):
        assert f"add column if not exists {field}" in sql


def test_migration_enforces_verified_atomic_save_and_report_ownership():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    save = sql.split("function public.save_quiz_pack_atomic", 1)[1]
    assert "verification_status' <> 'verified'" in save
    assert "micro-topic does not belong to its chapter" in save
    assert "current-affairs question" in save and "source_published_at is null" in save
    report = sql.split("function public.submit_question_report", 1)[1]
    assert "join public.quiz_attempt_answers" in report
    assert "a.user_id = p_user_id" in report
    assert "unique (question_id, user_id, attempt_id)" in sql
    assert "report rate limit exceeded" in report
    assert "status = 'under_review'" in report


def test_new_rpcs_are_server_only_and_security_invoker():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert sql.count("security invoker") >= 4
    assert "submit_question_report(uuid, text, uuid, text, text, text, integer)" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_every_new_foreign_key_has_a_covering_index():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for index in (
        "idx_question_verifications_source_document",
        "idx_question_generation_audits_subject",
        "idx_question_generation_audits_micro_topic",
        "idx_question_reports_quiz",
        "idx_question_reports_attempt",
    ):
        assert f"create index if not exists {index}" in sql
