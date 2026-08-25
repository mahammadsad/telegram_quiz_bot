from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services import content_replenishment_service, question_verification
from services.source_grounding import GroundingBundle, SourceDocument


def grounding(valid_questions) -> GroundingBundle:
    row = valid_questions[0]
    return GroundingBundle(
        subject_key="history",
        chapter="আধুনিক ভারত",
        micro_topic_id=row["micro_topic_id"],
        micro_topic_key=row["micro_topic_key"],
        micro_topic_name="আধুনিক ভারত — মূল ধারণা",
        documents=(
            SourceDocument(
                id=row["source_document_id"],
                url=row["source_url"],
                title=row["source_title"],
                domain=row["source_domain"],
                kind=row["source_kind"],
                published_at=row["source_published_at"],
                accessed_at=row["source_accessed_at"],
                fact_summary=row["evidence_summary"],
                fact_version=row["fact_version"],
                expires_at=None,
                micro_topic_id=row["micro_topic_id"],
                micro_topic_key=row["micro_topic_key"],
                micro_topic_name="আধুনিক ভারত — মূল ধারণা",
            ),
        ),
    )


def generated_candidates(valid_questions):
    rows = deepcopy(valid_questions[:5])
    for index, row in enumerate(rows):
        answer = row["options"][row["correct_index"]]
        row["canonical_claim"] = f"ঐতিহাসিক পরীক্ষামূলক তথ্য {index}: {answer}"
        row["knowledge_entity"] = f"entity-{index}"
        row["knowledge_relation"] = "has_value"
        row["knowledge_answer_value"] = answer
        row["knowledge_time_scope"] = "timeless"
        row["language_question_form"] = "generic_fact"
        row["language_verification_json"] = "{}"
        row["proof_family"] = "evidence_single_answer"
        row["proof_parameters_json"] = "{}"
        row["proof_option_values"] = list(row["options"])
        row["proof_option_units"] = [""] * 4
        row["proof_explanation_values"] = []
        row["proof_evidence_values"] = list(row["options"])
        row["proof_explanation_conclusion"] = answer
        for field in (
            "verification_status",
            "verification_score",
            "verification_notes",
            "verification_checks",
            "verified_at",
            "verification_model",
            "micro_topic_id",
            "source_url",
            "source_title",
            "source_domain",
            "source_kind",
            "source_published_at",
            "source_accessed_at",
            "evidence_summary",
            "fact_version",
            "language",
        ):
            row.pop(field, None)
    return rows


def verifier_results():
    return [
        {
            "question_number": index,
            "verdict": "rejected" if index == 3 else "verified",
            "confidence": 0.4 if index == 3 else 0.95,
            **{name: index != 3 for name in question_verification.CHECK_FIELDS},
            "notes": "Unsupported." if index == 3 else "Supported.",
        }
        for index in range(1, 6)
    ]


def test_zero_yield_job_backs_off_without_weakening_rejections(monkeypatch) -> None:
    now = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    job = {
        "id": "job-1",
        "subject_key": "mathematics",
        "micro_topic_id": "topic-1",
        "generation_batch_size": 5,
        "retry_count": 2,
    }
    completed: dict = {}

    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "ensure_due_replenishment_jobs",
        lambda **kwargs: [job],
    )
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "claim_replenishment_jobs",
        lambda **kwargs: [job],
    )
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "get_replenishment_bundle",
        lambda *args, **kwargs: [{"unused": True}],
    )
    monkeypatch.setattr(
        content_replenishment_service,
        "_bundle_from_rows",
        lambda rows: SimpleNamespace(chapter="সরলীকরণ"),
    )
    monkeypatch.setattr(
        content_replenishment_service,
        "generate_and_store_candidate_batch",
        lambda *args, **kwargs: content_replenishment_service.ReplenishmentBatchResult(
            [],
            [{"code": "math_family_unsupported"}] * 10,
            {"repair_attempted": True},
            {"accepted_count": 0},
        ),
    )

    def complete(**kwargs):
        completed.update(kwargs)
        return {"status": "retry_wait"}

    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "complete_replenishment_batch",
        complete,
    )

    result = content_replenishment_service.process_due_replenishment_jobs(
        object(), worker_id="worker", now=now, limit=1
    )

    assert result.outcomes == {"mathematics:topic-1": "retry_wait"}
    assert completed["accepted_count"] == 0
    assert completed["rejected_count"] == 10
    assert completed["rejection_codes"] == ["math_family_unsupported"]
    assert completed["error_code"] == "content_rejected"
    assert completed["retry_at"] == now + timedelta(minutes=60)


def test_replenishment_retry_backoff_is_capped() -> None:
    now = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)

    assert content_replenishment_service._replenishment_retry_at(now, 0) == now + timedelta(minutes=15)
    assert content_replenishment_service._replenishment_retry_at(now, 20) == now + timedelta(hours=6)


def test_repair_prompt_gives_static_code_specific_guidance() -> None:
    prompt = content_replenishment_service._candidate_repair_prompt(
        "base",
        {
            "math_family_unsupported",
            "reasoning_proof_invalid",
            "answer_not_unique",
            "answer_leakage",
            "option_pattern_leakage",
            "translation_review_required",
            "language_form_invalid",
            "historical_duplicate",
        },
    )

    assert "never invent a geometry" in prompt
    assert "gcd_lcm" in prompt
    assert "none of the three distractor values" in prompt
    assert "equivalent fractions" in prompt
    assert "fully constrained instance" in prompt
    assert "correct option text in the question stem" in prompt
    assert "one consistent visible representation" in prompt
    assert "translation_status not_applicable" in prompt
    assert "language_question_form must be exactly" in prompt
    assert "separate real operator attestation" in prompt
    assert "different supplied atomic fact" in prompt


def test_replenishment_preserves_verified_candidates_and_logs_hash_only(monkeypatch, valid_questions):
    responses = [json.dumps(generated_candidates(valid_questions)), json.dumps(verifier_results())]

    class Pool:
        def generate_subject_quiz(self, **kwargs):
            return responses.pop(0), {
                "provider": "primary",
                "model": "test-model",
                "attempts": 1,
            }

    captured = {}

    def save(rows, context):
        captured["rows"] = rows
        captured["context"] = context
        return {"accepted_count": len(rows), "question_ids": ["saved"] * len(rows)}

    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "save_verified_candidates",
        save,
    )
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "existing_candidate_identities",
        lambda **kwargs: (set(), set(), set()),
    )
    result = content_replenishment_service.generate_and_store_candidate_batch(
        "history",
        "আধুনিক ভারত",
        grounding(valid_questions),
        Pool(),
        batch_size=5,
    )
    assert len(result.accepted) == 4
    assert len(captured["rows"]) == 4
    assert all(len(row["knowledge_key"]) == 64 for row in captured["rows"])
    assert all(len(row["variant_fingerprint"]) == 64 for row in captured["rows"])
    assert result.generation_context["candidate_count"] == 5
    assert result.generation_context["accepted_count"] == 4
    assert len(result.generation_context["prompt_hash"]) == 64
    assert "prompt" not in result.generation_context
    assert "verification_failed" in result.generation_context["rejection_codes"]


def test_candidate_contract_exposes_subject_specific_proof_artifacts(valid_questions) -> None:
    required = set(content_replenishment_service.CANDIDATE_JSON_SCHEMA["items"]["required"])
    assert {
        "language_question_form",
        "language_verification_json",
        "proof_option_units",
        "proof_explanation_values",
        "proof_evidence_span",
    } <= required
    base_properties = content_replenishment_service.CANDIDATE_JSON_SCHEMA["items"][
        "properties"
    ]
    assert base_properties["options"]["minItems"] == 4
    assert base_properties["options"]["maxItems"] == 4
    assert base_properties["correct_index"]["minimum"] == 0
    assert base_properties["correct_index"]["maximum"] == 3
    assert base_properties["difficulty"]["enum"] == ["easy", "medium", "hard"]

    prompt = content_replenishment_service._candidate_prompt("history", "আধুনিক ভারত", grounding(valid_questions), 3)
    assert "algebra_linear" in prompt
    assert "time_work" in prompt
    assert "ordering_constraints" in prompt
    assert "syllogism_finite_sets" in prompt
    assert "uncertain bengali" in prompt.lower()
    assert "must not use the Bengali translation form" in prompt
    assert "evidence_span_single_answer" in prompt
    assert "contiguous span" in prompt
    assert "exact original spelling" in prompt
    assert "translation or transliteration" in prompt

    english_schema = content_replenishment_service._candidate_schema("english")
    english_properties = english_schema["items"]["properties"]
    assert english_properties["language_question_form"]["enum"] == [
        "grammar_rule",
        "vocabulary",
        "comprehension",
        "error_detection",
    ]
    assert english_properties["proof_family"]["enum"] == [
        "evidence_span_single_answer"
    ]
    language_artifact = english_properties["language_verification_json"]
    assert language_artifact["type"] == "OBJECT"
    assert language_artifact["properties"]["review_status"]["enum"] == [
        "source_proved"
    ]
    assert language_artifact["properties"]["version"]["minimum"] == 1
    assert language_artifact["properties"]["version"]["maximum"] == 1
    assert language_artifact["properties"]["uncertain"] == {"type": "BOOLEAN"}

    math_schema = content_replenishment_service._candidate_schema("mathematics")
    math_properties = math_schema["items"]["properties"]
    assert "arithmetic_expression" in math_properties["proof_family"]["enum"]
    assert "evidence_span_single_answer" in math_properties["proof_family"]["enum"]
    assert "fraction_operation" not in math_properties["proof_family"]["enum"]
    assert math_properties["language_question_form"]["enum"] == ["generic_fact"]
    assert math_properties["language_verification_json"]["type"] == "STRING"

    reasoning_schema = content_replenishment_service._candidate_schema("reasoning")
    reasoning_properties = reasoning_schema["items"]["properties"]
    assert "syllogism_finite_sets" in reasoning_properties["proof_family"]["enum"]
    assert "evidence_span_single_answer" in reasoning_properties["proof_family"]["enum"]
    assert "categorical_syllogism" not in reasoning_properties["proof_family"]["enum"]

    assert "enum" not in content_replenishment_service.CANDIDATE_JSON_SCHEMA[
        "items"
    ]["properties"]["proof_family"]


def test_language_artifact_is_derived_only_from_exact_verified_span(valid_questions) -> None:
    bundle = grounding(valid_questions)
    item = generated_candidates(valid_questions)[0]
    exact_span = bundle.documents[0].fact_summary[:80]
    item.update(
        language_question_form="Literature Fact",
        language_verification_json=json.dumps(
            {"uncertain": False, "source_span": "model paraphrase"}
        ),
        proof_evidence_span=exact_span,
    )

    enriched = content_replenishment_service._enrich(
        [item], "bengali", "আধুনিক ভারত", bundle
    )[0]

    assert enriched["language_question_form"] == "literature"
    artifact = enriched["language_verification"]
    assert artifact["source_span"] == exact_span
    assert artifact["review_status"] == "source_proved"
    assert artifact["uncertain"] is False
    assert artifact["rule_id"].startswith("source-span-")

    item["proof_evidence_span"] = "not in the verified source"
    invalid = content_replenishment_service._enrich(
        [item], "bengali", "আধুনিক ভারত", bundle
    )[0]
    assert invalid["language_verification"]["source_span"] == "model paraphrase"

def test_language_form_normalization_does_not_promote_generic_content() -> None:
    assert content_replenishment_service._normalized_language_form(
        "Grammar Question", "english"
    ) == "grammar_rule"
    assert content_replenishment_service._normalized_language_form(
        "generic_fact", "bengali"
    ) == "generic_fact"
    assert content_replenishment_service._normalized_language_form(
        "generic_fact", "bengali", "bengali:phonetics:t02"
    ) == "linguistics"
    assert content_replenishment_service._normalized_language_form(
        "generic_fact", "english", "english:error-correction:t01"
    ) == "error_detection"


def test_replenishment_excludes_historical_identity_from_job_progress(monkeypatch, valid_questions) -> None:
    responses = [json.dumps(generated_candidates(valid_questions)), json.dumps(verifier_results())]

    class Pool:
        def generate_subject_quiz(self, **kwargs):
            return responses.pop(0), {"provider": "primary", "model": "test-model", "attempts": 1}

    def existing(**kwargs):
        return ({kwargs["variant_fingerprints"][0]}, set(), set())

    saved: list[dict] = []
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "existing_candidate_identities",
        existing,
    )
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "save_verified_candidates",
        lambda rows, context: saved.extend(rows) or {"accepted_count": len(rows)},
    )

    result = content_replenishment_service.generate_and_store_candidate_batch(
        "history",
        "আধুনিক ভারত",
        grounding(valid_questions),
        Pool(),
        batch_size=5,
    )

    assert len(result.accepted) == 3
    assert len(saved) == 3
    assert "historical_duplicate" in result.generation_context["rejection_codes"]


def test_replenishment_repairs_a_fully_rejected_batch_without_weakening_checks(monkeypatch, valid_questions) -> None:
    invalid = generated_candidates(valid_questions)
    for row in invalid:
        row["options"] = ["একই বিকল্প"] * 4
        row["proof_option_values"] = list(row["options"])
        row["proof_evidence_values"] = list(row["options"])
        row["proof_explanation_conclusion"] = "একই বিকল্প"
    verification = [
        {
            "question_number": index,
            "verdict": "verified",
            "confidence": 0.98,
            **{name: True for name in question_verification.CHECK_FIELDS},
            "notes": "Supported.",
        }
        for index in range(1, 6)
    ]
    responses = [
        json.dumps(invalid),
        json.dumps(generated_candidates(valid_questions)),
        json.dumps(verification),
    ]
    prompts: list[str] = []

    class Pool:
        def generate_subject_quiz(self, **kwargs):
            prompts.append(kwargs["prompt"])
            return responses.pop(0), {
                "provider": "primary",
                "model": "test-model",
                "attempts": 1,
            }

    saved: list[dict] = []
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "save_verified_candidates",
        lambda rows, context: saved.extend(rows) or {"accepted_count": len(rows)},
    )
    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "existing_candidate_identities",
        lambda **kwargs: (set(), set(), set()),
    )

    result = content_replenishment_service.generate_and_store_candidate_batch(
        "history",
        "আধুনিক ভারত",
        grounding(valid_questions),
        Pool(),
        batch_size=5,
    )

    assert len(result.accepted) == 5
    assert len(saved) == 5
    assert result.generation_context["candidate_count"] == 10
    assert result.generation_context["repair_attempted"] is True
    assert result.generation_context["attempts"] == 2
    assert "previous candidate batch was rejected" in prompts[1].lower()
    assert len(prompts) == 3  # two generator calls and one independent verifier call


def test_replenishment_retries_malformed_generation_once_without_verifier(monkeypatch, valid_questions) -> None:
    calls = 0

    class Pool:
        def generate_subject_quiz(self, **kwargs):
            nonlocal calls
            calls += 1
            return "not-json", {"provider": "primary", "model": "test-model", "attempts": 1}

    monkeypatch.setattr(
        content_replenishment_service.content_inventory_repo,
        "save_verified_candidates",
        lambda rows, context: {"accepted_count": len(rows)},
    )

    try:
        content_replenishment_service.generate_and_store_candidate_batch(
            "history",
            "আধুনিক ভারত",
            grounding(valid_questions),
            Pool(),
            batch_size=5,
        )
    except ValueError as exc:
        assert "invalid candidate batch" in str(exc)
    else:
        raise AssertionError("malformed candidate generation must fail closed")
    assert calls == 2
