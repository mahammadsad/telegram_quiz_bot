from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from services.content_identity import (
    canonical_knowledge_identity,
    knowledge_key,
    variant_fingerprint,
)
from services.question_validation import validate_question_candidates

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808140838_phase_c_content_identity_foundation.sql"
)
INVENTORY_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808140843_phase_c_inventory_jobs_and_usage.sql"
)
CANDIDATE_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808140850_phase_c_verified_candidate_persistence.sql"
)


def test_paraphrase_and_inverse_relation_share_knowledge_identity() -> None:
    direct = knowledge_key(
        subject="geography",
        entity="France",
        relation="capital_of",
        answer_value="Paris",
    )
    paraphrase = knowledge_key(
        subject="Geography",
        entity="France!",
        relation="has_capital",
        answer_value="PARIS",
    )
    inverse = knowledge_key(
        subject="geography",
        entity="Paris",
        relation="is_capital_of",
        answer_value="France",
    )
    assert direct == paraphrase == inverse


def test_canonical_identity_fields_close_inverse_wording_bypass() -> None:
    direct = canonical_knowledge_identity({
        "subject_key": "geography",
        "knowledge_entity": "France",
        "knowledge_relation": "has_capital",
        "knowledge_answer_value": "Paris",
    })
    inverse = canonical_knowledge_identity({
        "subject_key": "geography",
        "knowledge_entity": "Paris",
        "knowledge_relation": "is_capital_of",
        "knowledge_answer_value": "France",
    })
    assert direct == inverse
    assert direct["entity_key"] == "france"
    assert direct["relation_key"] == "capital_of"


def test_mutable_metadata_does_not_change_variant_fingerprint() -> None:
    content = {
        "stem": "ফ্রান্সের রাজধানী কোনটি?",
        "options": ["প্যারিস", "রোম", "বার্লিন", "মাদ্রিদ"],
        "correct_index": 0,
        "language": "bn",
    }
    first = variant_fingerprint(**content)
    mutated_metadata = {
        **content,
        "source_accessed_at": "2026-08-08T10:00:00Z",
        "verification_model": "new-verifier",
        "usage_count": 99,
    }
    second = variant_fingerprint(
        **{key: mutated_metadata[key] for key in content}
    )
    assert first == second


def test_variant_fingerprint_changes_when_displayed_answer_changes() -> None:
    original = variant_fingerprint(
        stem="ফ্রান্সের রাজধানী কোনটি?",
        options=["প্যারিস", "রোম", "বার্লিন", "মাদ্রিদ"],
        correct_index=0,
        language="bn",
    )
    changed = variant_fingerprint(
        stem="ফ্রান্সের রাজধানী কোনটি?",
        options=["লিয়ন", "রোম", "বার্লিন", "মাদ্রিদ"],
        correct_index=0,
        language="bn",
    )
    assert original != changed


def test_nine_valid_candidates_survive_one_rejection(valid_questions) -> None:
    candidates = deepcopy(valid_questions)
    candidates[4]["options"][1] = candidates[4]["options"][0]
    accepted, rejected = validate_question_candidates(
        candidates,
        "history",
        "আধুনিক ভারত",
    )
    assert len(accepted) == 9
    assert rejected == [{
        "index": 4,
        "code": "options_duplicate",
        "message": "Question 1 contains duplicate options.",
    }]


def test_candidate_answer_leakage_has_actionable_rejection_code(valid_questions) -> None:
    candidate = deepcopy(valid_questions[0])
    answer = candidate["options"][candidate["correct_index"]]
    candidate["question"] = f"{answer} উত্তরটি কোন বিকল্পে লেখা আছে?"

    accepted, rejected = validate_question_candidates(
        [candidate],
        "history",
        "আধুনিক ভারত",
    )

    assert accepted == []
    assert rejected[0]["code"] == "answer_leakage"


def test_identity_rejects_incomplete_semantic_fields() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        knowledge_key(
            subject="history",
            entity="",
            relation="founded_by",
            answer_value="test",
        )


def test_phase_c_migration_is_additive_private_and_indexed() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "knowledge_points",
        "source_facts",
        "knowledge_point_evidence",
        "question_generation_contexts",
        "content_verification_artifacts",
        "content_usage_events",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql
    for column in (
        "knowledge_point_id",
        "variant_fingerprint",
        "question_form",
        "inventory_status",
        "eligible_at",
    ):
        assert f"add column if not exists {column}" in sql
    assert "idx_questions_variant_fingerprint_unique" in sql
    assert "security invoker" in sql
    assert "security definer" not in sql
    assert "get_phase_c_content_contract" in sql


def test_append_only_artifacts_block_update_and_delete() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "content_verification_artifacts",
        "content_usage_events",
        "question_generation_contexts",
    ):
        assert f"before update or delete on public.{table}" in sql
    assert "raise exception '% is append-only'" in sql


def test_inventory_jobs_are_durable_private_and_small_batch() -> None:
    sql = INVENTORY_MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "content_replenishment_jobs",
        "content_replenishment_job_events",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql
    assert "target_candidate_count between 12 and 15" in sql
    assert "generation_batch_size between 3 and 5" in sql
    assert "for update skip locked" in sql
    assert "before update or delete on public.content_replenishment_job_events" in sql
    assert "security definer" not in sql
    assert "get_phase_c_inventory_contract" in sql


def test_post_usage_and_inventory_reads_are_atomic_and_fail_closed() -> None:
    sql = INVENTORY_MIGRATION.read_text(encoding="utf-8").lower()
    assert "after update of status on public.quiz_runs" in sql
    assert "on conflict (question_id, quiz_id, event_type)" in sql
    inventory = sql.split("function public.get_verified_question_inventory", 1)[1]
    assert "question.inventory_status in ('verified','used')" in inventory
    assert "fact.verification_status = 'verified'" in inventory
    assert "not fact.review_required" in inventory
    assert "fact.expires_at is null or fact.expires_at >= p_now" in inventory


def test_candidate_persistence_recomputes_every_stable_identity() -> None:
    sql = CANDIDATE_MIGRATION.read_text(encoding="utf-8").lower()
    for function in (
        "knowledge_identity_hash",
        "question_variant_fingerprint",
        "source_fact_identity_hash",
        "save_verified_content_candidates",
    ):
        assert f"function public.{function}" in sql
    save = sql.split("function public.save_verified_content_candidates", 1)[1]
    assert "public.knowledge_identity_hash(v_item)" in save
    assert "public.question_variant_fingerprint(v_item)" in save
    assert "public.source_fact_identity_hash(v_item)" in save
    assert "source.verification_status = 'verified'" in save
    assert "content_verification_artifacts" in save
    assert "inventory_status = 'verified'" in save
    assert "security definer" not in sql


def test_candidate_persistence_is_server_only() -> None:
    sql = CANDIDATE_MIGRATION.read_text(encoding="utf-8").lower()
    signature = "public.save_verified_content_candidates(jsonb,jsonb)"
    assert f"revoke all on function {signature} from public, anon, authenticated" in sql
    assert f"grant execute on function {signature} to service_role" in sql
