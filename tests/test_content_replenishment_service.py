from __future__ import annotations

import json
from copy import deepcopy

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
        documents=(SourceDocument(
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
        ),),
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
            "verification_status", "verification_score", "verification_notes",
            "verification_checks", "verified_at", "verification_model",
            "micro_topic_id", "source_url", "source_title", "source_domain",
            "source_kind", "source_published_at", "source_accessed_at",
            "evidence_summary", "fact_version", "language",
        ):
            row.pop(field, None)
    return rows


def verifier_results():
    return [
        {
            "question_number": index,
            "verdict": "rejected" if index == 3 else "verified",
            "confidence": 0.4 if index == 3 else 0.95,
            **{
                name: index != 3
                for name in question_verification.CHECK_FIELDS
            },
            "notes": "Unsupported." if index == 3 else "Supported.",
        }
        for index in range(1, 6)
    ]


def test_replenishment_preserves_verified_candidates_and_logs_hash_only(
    monkeypatch, valid_questions
):
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
    } <= required

    prompt = content_replenishment_service._candidate_prompt(
        "history", "আধুনিক ভারত", grounding(valid_questions), 3
    )
    assert "algebra_linear" in prompt
    assert "time_work" in prompt
    assert "ordering_constraints" in prompt
    assert "syllogism_finite_sets" in prompt
    assert "uncertain bengali" in prompt.lower()
