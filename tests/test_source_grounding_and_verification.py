from __future__ import annotations

import json
from copy import deepcopy
from datetime import date

import pytest

from services import question_verification, source_grounding
from services.question_validation import QuizValidationError
from services.source_grounding import GroundingBundle, SourceDocument


def source_row(**overrides):
    row = {
        "source_document_id": "22222222-2222-4222-8222-222222222222",
        "micro_topic_id": "11111111-1111-4111-8111-111111111111",
        "micro_topic_key": "current-affairs:national:appointments",
        "micro_topic_name": "জাতীয় নিয়োগ",
        "source_url": "https://pib.gov.in/PressReleasePage.aspx?PRID=1",
        "source_title": "Official appointment release",
        "source_domain": "pib.gov.in",
        "source_kind": "official",
        "source_published_at": "2026-07-10T09:00:00+00:00",
        "source_accessed_at": "2026-07-18T09:00:00+00:00",
        "fact_summary": "The official release names the appointee, office, and effective date in explicit terms.",
        "fact_version": "2026-07-10",
        "expires_at": "2026-08-10T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def bundle():
    row = source_row()
    return GroundingBundle(
        subject_key="current-affairs",
        chapter="জাতীয় সাম্প্রতিক ঘটনা",
        micro_topic_id=row["micro_topic_id"],
        micro_topic_key=row["micro_topic_key"],
        micro_topic_name=row["micro_topic_name"],
        documents=(SourceDocument(
            id=row["source_document_id"],
            url=row["source_url"],
            title=row["source_title"],
            domain=row["source_domain"],
            kind=row["source_kind"],
            published_at=row["source_published_at"],
            accessed_at=row["source_accessed_at"],
            fact_summary=row["fact_summary"],
            fact_version=row["fact_version"],
            expires_at=row["expires_at"],
        ),),
    )


def test_current_affairs_requires_recent_primary_or_official_dated_source(monkeypatch):
    monkeypatch.setattr(
        source_grounding.source_documents_repo,
        "list_grounding_bundle",
        lambda *args, **kwargs: [source_row()],
    )
    loaded = source_grounding.load_grounding_bundle(
        "current-affairs", "জাতীয় সাম্প্রতিক ঘটনা", date(2026, 7, 18)
    )
    assert loaded.documents[0].domain == "pib.gov.in"

    monkeypatch.setattr(
        source_grounding.source_documents_repo,
        "list_grounding_bundle",
        lambda *args, **kwargs: [source_row(source_published_at=None)],
    )
    with pytest.raises(QuizValidationError, match="publication date"):
        source_grounding.load_grounding_bundle(
            "current-affairs", "জাতীয় সাম্প্রতিক ঘটনা", date(2026, 7, 18)
        )


def test_grounding_fails_closed_without_verified_source_rows(monkeypatch):
    monkeypatch.setattr(
        source_grounding.source_documents_repo,
        "list_grounding_bundle",
        lambda *args, **kwargs: [],
    )
    with pytest.raises(QuizValidationError, match="No verified source facts"):
        source_grounding.load_grounding_bundle("history", "আধুনিক ভারত", date(2026, 7, 18))


def test_independent_verifier_rejects_any_failed_check(valid_questions):
    results = []
    for index in range(1, 11):
        results.append({
            "question_number": index,
            "verdict": "verified",
            "confidence": 0.95,
            **{name: True for name in question_verification.CHECK_FIELDS},
            "notes": "Supported.",
        })
    results[3]["unambiguous"] = False
    results[3]["verdict"] = "rejected"

    class Pool:
        def generate_subject_quiz(self, **kwargs):
            return json.dumps(results), {"provider": "primary", "model": "verifier", "attempts": 1}

    generated = deepcopy(valid_questions)
    for row in generated:
        row["verification_status"] = "generated"
    with pytest.raises(QuizValidationError, match="rejected the quiz"):
        question_verification.verify_questions(generated, bundle(), Pool())


def test_rejected_verifier_output_is_persisted_for_audit(monkeypatch, valid_questions):
    results = [{
        "question_number": index,
        "verdict": "rejected" if index == 1 else "verified",
        "confidence": 0.4 if index == 1 else 0.95,
        **{name: index != 1 for name in question_verification.CHECK_FIELDS},
        "notes": "Unsupported answer." if index == 1 else "Supported.",
    } for index in range(1, 11)]

    class Pool:
        def generate_subject_quiz(self, **kwargs):
            return json.dumps(results), {"provider": "primary", "model": "verifier", "attempts": 1}

    audits = []
    monkeypatch.setattr(
        question_verification.verification_audits_repo,
        "record",
        lambda **kwargs: audits.append(kwargs),
    )
    with pytest.raises(QuizValidationError):
        question_verification.verify_questions(
            valid_questions,
            bundle(),
            Pool(),
            quiz_id="20260718-current-affairs",
        )
    assert len(audits) == 1
    assert audits[0]["verdict"] == "rejected"
    assert audits[0]["rejection_reasons"]
