from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from services import inventory_quiz_service

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)


def database_rows(valid_questions):
    rows = []
    for index, item in enumerate(deepcopy(valid_questions)):
        rows.append({
            "id": f"question-{index}",
            "question_text": item["question"],
            "option_a": item["options"][0],
            "option_b": item["options"][1],
            "option_c": item["options"][2],
            "option_d": item["options"][3],
            "correct_option": "ABCD"[item["correct_index"]],
            "explanation": item["explanation"],
            "detailed_explanation": item["detailed_explanation"],
            "subject": item["subject_key"],
            "topic": item["chapter"],
            "topic_key": item["micro_topic_key"],
            "micro_topic_id": item["micro_topic_id"],
            "micro_topic_key": item["micro_topic_key"],
            "source_document_id": item["source_document_id"],
            "source_url": item["source_url"],
            "source_title": item["source_title"],
            "source_domain": item["source_domain"],
            "source_kind": item["source_kind"],
            "source_published_at": item["source_published_at"],
            "source_accessed_at": item["source_accessed_at"],
            "evidence_summary": item["evidence_summary"],
            "fact_version": item["fact_version"],
            "difficulty": item["difficulty"],
            "language": item["language"],
            "verification_status": "verified",
            "verification_score": item["verification_score"],
            "verification_notes": item["verification_notes"],
            "verification_checks": item["verification_checks"],
            "verified_at": item["verified_at"],
            "verification_model": item["verification_model"],
            "status": "active",
            "inventory_status": "verified",
            "review_required": False,
            "knowledge_point_id": f"knowledge-{index}",
            "variant_fingerprint": f"variant-{index}",
            "eligible_at": "2026-08-01T00:00:00+00:00",
            "created_at": "2026-07-01T00:00:00+00:00",
        })
    return rows


def test_due_time_uses_verified_inventory_without_generation(monkeypatch, valid_questions) -> None:
    rows = database_rows(valid_questions)
    monkeypatch.setattr(
        inventory_quiz_service.content_inventory_repo,
        "list_verified_candidates",
        lambda *args, **kwargs: rows,
    )
    monkeypatch.setattr(
        inventory_quiz_service.content_inventory_repo,
        "list_recent_usage",
        lambda *args, **kwargs: [],
    )
    result = inventory_quiz_service.load_verified_inventory_quiz(
        "history", "আধুনিক ভারত", now=NOW
    )
    assert result is not None
    assert len(result.questions) == 10
    assert result.relaxed_constraints == ()


def test_invalid_inventory_fails_closed_for_gemini_fallback(monkeypatch, valid_questions) -> None:
    rows = database_rows(valid_questions)
    rows[0]["inventory_status"] = "quarantined"
    monkeypatch.setattr(
        inventory_quiz_service.content_inventory_repo,
        "list_verified_candidates",
        lambda *args, **kwargs: rows,
    )
    monkeypatch.setattr(
        inventory_quiz_service.content_inventory_repo,
        "list_recent_usage",
        lambda *args, **kwargs: [],
    )
    assert inventory_quiz_service.load_verified_inventory_quiz(
        "history", "আধুনিক ভারত", now=NOW
    ) is None
