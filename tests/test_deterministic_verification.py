from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from services.deterministic_verification import (
    DeterministicVerificationError,
    verify_candidate,
)
from services.question_validation import validate_question_candidates


def mathematics_candidate() -> dict:
    return {
        "subject_key": "mathematics",
        "question": "১০০-এর ২৫ শতাংশ কত?",
        "options": ["১০", "২০", "২৫", "৩০"],
        "correct_index": 2,
        "explanation": "শতাংশের নিয়মে সঠিক উত্তর ২৫।",
        "detailed_explanation": "১০০ × ২৫ ÷ ১০০ = ২৫, তাই সঠিক উত্তর ২৫।",
        "language": "bn",
        "deterministic_proof": {
            "version": 1,
            "family": "percentage_of",
            "parameters": {"base": "100", "percent": "25"},
            "option_values": ["10", "20", "25", "30"],
            "explanation_conclusion": "২৫",
        },
    }


def reasoning_candidate() -> dict:
    return {
        "subject_key": "reasoning",
        "question": "ধারাটির পরের সংখ্যা কী: ২, ৫, ৮, ১১?",
        "options": ["১২", "১৩", "১৪", "১৫"],
        "correct_index": 2,
        "explanation": "প্রতি ধাপে ৩ যোগ হয়েছে, তাই উত্তর ১৪।",
        "detailed_explanation": "পার্থক্য ৩, ৩, ৩; পরের সংখ্যা ১১ + ৩ = ১৪।",
        "language": "bn",
        "deterministic_proof": {
            "version": 1,
            "family": "arithmetic_series_next",
            "parameters": {"sequence": [2, 5, 8, 11]},
            "option_values": [12, 13, 14, 15],
            "explanation_conclusion": "১৪",
        },
    }


def evidence_candidate() -> dict:
    return {
        "subject_key": "geography",
        "question": "পশ্চিমবঙ্গের রাজধানী কোনটি?",
        "options": ["কলকাতা", "দিল্লি", "পাটনা", "রাঁচি"],
        "correct_index": 0,
        "explanation": "যাচাইকৃত তথ্য অনুযায়ী উত্তর কলকাতা।",
        "detailed_explanation": "উৎসে পশ্চিমবঙ্গের রাজধানী হিসেবে কলকাতা লেখা আছে।",
        "language": "bn",
        "canonical_claim": "পশ্চিমবঙ্গের রাজধানী কলকাতা।",
        "evidence_summary": "সরকারি উৎসে পশ্চিমবঙ্গের রাজধানী কলকাতা বলা হয়েছে।",
        "knowledge_answer_value": "কলকাতা",
        "deterministic_proof": {
            "version": 1,
            "family": "evidence_single_answer",
            "parameters": {},
            "option_values": ["কলকাতা", "দিল্লি", "পাটনা", "রাঁচি"],
            "evidence_values": ["কলকাতা", "দিল্লি", "পাটনা", "রাঁচি"],
            "explanation_conclusion": "কলকাতা",
        },
    }


def test_mathematics_solver_proves_one_answer() -> None:
    result = verify_candidate(mathematics_candidate())

    assert result.family == "percentage_of"
    assert result.expected_answer == "২৫"
    assert result.checks["unique_answer_proved"] is True


def test_atomic_evidence_must_support_exactly_one_answer() -> None:
    assert verify_candidate(evidence_candidate()).expected_answer == "কলকাতা"
    ambiguous = evidence_candidate()
    ambiguous["evidence_summary"] += " পুরনো তালিকায় দিল্লিও লেখা আছে।"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(ambiguous)

    assert raised.value.code == "answer_not_unique"


def test_wrong_declared_answer_is_rejected() -> None:
    candidate = mathematics_candidate()
    candidate["correct_index"] = 1

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "declared_answer_wrong"


def test_two_correct_options_are_rejected() -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"]["option_values"] = [10, 25, 25, 30]

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "answer_not_unique"


def test_materially_duplicate_and_pattern_leaking_options_are_rejected() -> None:
    duplicate = mathematics_candidate()
    duplicate["options"] = ["বিকল্প ক: ২৫", "২৫", "৩০", "৪০"]
    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(duplicate)
    assert raised.value.code == "options_materially_duplicate"

    leakage = mathematics_candidate()
    leakage["options"] = ["দশ", "বিশ", "25", "ত্রিশ"]
    leakage["deterministic_proof"]["explanation_conclusion"] = "25"
    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(leakage)
    assert raised.value.code == "option_pattern_leakage"


def test_explanation_contradiction_is_rejected() -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"]["explanation_conclusion"] = "৩০"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "explanation_contradiction"


def test_stale_fact_is_rejected() -> None:
    candidate = mathematics_candidate()
    candidate["source_expires_at"] = "2026-08-07T00:00:00+00:00"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(
            candidate,
            now=datetime(2026, 8, 8, tzinfo=timezone.utc),
        )

    assert raised.value.code == "source_stale"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"question": "à¦­à¦¾à¦·à¦¾?"}, "language_encoding_invalid"),
        (
            {"terminology_glossary": {"সংবিধান": "সংবিধানী"}},
            "translation_mismatch",
        ),
    ],
)
def test_bengali_encoding_and_terminology_problems_are_rejected(
    overrides: dict,
    code: str,
) -> None:
    candidate = mathematics_candidate()
    candidate.update(overrides)

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == code


def test_invalid_mathematics_is_rejected() -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": "arithmetic_expression",
        "parameters": {"values": [10, 0], "operators": ["/"]},
        "option_values": [0, 1, 10, 100],
        "explanation_conclusion": "১০",
    }

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "math_proof_invalid"


def test_reasoning_solver_rejects_inconsistent_puzzle() -> None:
    valid = reasoning_candidate()
    assert verify_candidate(valid).expected_answer == "১৪"
    invalid = deepcopy(valid)
    invalid["deterministic_proof"]["parameters"]["sequence"] = [2, 5, 9, 11]

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(invalid)

    assert raised.value.code == "reasoning_proof_invalid"


def test_duplicate_current_affairs_event_is_rejected_by_knowledge_point(
    valid_questions,
) -> None:
    first = deepcopy(valid_questions[0])
    second = deepcopy(valid_questions[1])
    for row in (first, second):
        row.update({
            "subject_key": "current-affairs",
            "chapter": "জাতীয় সাম্প্রতিক ঘটনা",
            "canonical_claim": "একই দপ্তরে একই ব্যক্তির নিয়োগ",
            "knowledge_entity": "office-x",
            "knowledge_relation": "appointed_person",
            "knowledge_answer_value": "person-y",
            "knowledge_time_scope": "2026-08",
        })

    accepted, rejected = validate_question_candidates(
        [first, second],
        "current-affairs",
        "জাতীয় সাম্প্রতিক ঘটনা",
    )

    assert len(accepted) == 1
    assert rejected == [{
        "index": 1,
        "code": "duplicate_knowledge_point",
        "message": "Candidate duplicates a knowledge point already accepted in this batch.",
    }]
