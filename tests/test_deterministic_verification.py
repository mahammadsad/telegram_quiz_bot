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
            "explanation_values": ["25"],
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
            "explanation_values": [3, 14],
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


def test_mathematics_concept_can_use_exact_source_evidence() -> None:
    candidate = evidence_candidate()
    candidate["subject_key"] = "mathematics"
    candidate["deterministic_proof"].update(
        family="evidence_span_single_answer",
        evidence_span="পশ্চিমবঙ্গের রাজধানী কলকাতা",
    )

    result = verify_candidate(candidate)

    assert result.family == "evidence_span_single_answer"
    assert result.expected_answer == candidate["options"][candidate["correct_index"]]
    assert result.checks["unique_answer_proved"] is True


def test_atomic_evidence_must_support_exactly_one_answer() -> None:
    assert verify_candidate(evidence_candidate()).expected_answer == "কলকাতা"
    ambiguous = evidence_candidate()
    ambiguous["evidence_summary"] += " পুরনো তালিকায় দিল্লিও লেখা আছে।"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(ambiguous)

    assert raised.value.code == "answer_not_unique"


def test_exact_evidence_span_is_atomic_inside_a_broader_source() -> None:
    candidate = evidence_candidate()
    candidate["evidence_summary"] += " অন্য প্রসঙ্গে দিল্লির কথাও লেখা আছে।"
    candidate["deterministic_proof"]["family"] = "evidence_span_single_answer"
    candidate["deterministic_proof"]["evidence_span"] = "সরকারি উৎসে পশ্চিমবঙ্গের রাজধানী কলকাতা বলা হয়েছে।"

    assert verify_candidate(candidate).expected_answer == "কলকাতা"

    candidate["deterministic_proof"]["evidence_span"] = "পশ্চিমবঙ্গের রাজধানী কলকাতা।"
    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)
    assert raised.value.code == "evidence_span_invalid"


def test_exact_evidence_span_rejects_a_second_displayed_answer() -> None:
    candidate = evidence_candidate()
    candidate["evidence_summary"] += " পুরনো তালিকায় দিল্লিও লেখা আছে।"
    candidate["deterministic_proof"]["family"] = "evidence_span_single_answer"
    candidate["deterministic_proof"]["evidence_span"] = candidate["evidence_summary"]

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)
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


def test_model_verified_candidate_records_pattern_signal_without_hard_failure() -> None:
    candidate = mathematics_candidate()
    candidate["options"] = ["দশ", "বিশ", "25", "ত্রিশ"]
    candidate["deterministic_proof"]["explanation_conclusion"] = "25"

    result = verify_candidate(candidate, require_subject_proof=False)

    assert result.checks["option_pattern_safe"] is False
    assert result.checks["unique_answer_proved"] is True


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


@pytest.mark.parametrize(
    ("family", "parameters", "option_values", "explanation_values", "answer"),
    [
        ("algebra_linear", {"coefficient": 3, "constant": 6, "right_hand_side": 21}, [3, 4, 5, 6], [15, 5], "৫"),
        (
            "profit_loss",
            {"cost_price": 100, "selling_price": 125, "requested": "profit_percent"},
            [20, 25, 30, 35],
            [25, 25],
            "২৫",
        ),
        (
            "rounded_division",
            {"numerator": 2, "denominator": 3, "decimal_places": 2, "rounding_mode": "half_up"},
            ["0.66", "0.67", "0.68", "0.69"],
            ["0.67"],
            "০.৬৭",
        ),
    ],
)
def test_extended_mathematics_families_are_solved(
    family: str,
    parameters: dict,
    option_values: list,
    explanation_values: list,
    answer: str,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = ["৩", "৪", answer, "৬"] if family == "algebra_linear" else ["২০", answer, "৩০", "৩৫"]
    if family == "rounded_division":
        candidate["options"] = ["০.৬৬", "০.৬৭", "০.৬৮", "০.৬৯"]
        candidate["correct_index"] = 1
    else:
        candidate["correct_index"] = 2 if family == "algebra_linear" else 1
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": option_values,
        "explanation_values": explanation_values,
        "explanation_conclusion": candidate["options"][candidate["correct_index"]],
    }
    if family == "profit_loss":
        candidate["deterministic_proof"]["option_units"] = ["percent"] * 4

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "option_values", "trace", "units", "correct"),
    [
        (
            "gcd_lcm",
            {"values": [18, 24], "requested": "gcd"},
            ["৩", "৬", "৯", "১২"],
            [3, 6, 9, 12],
            [6],
            None,
            1,
        ),
        (
            "exact_square_root",
            {"radicand": 144},
            ["১০", "১১", "১২", "১৩"],
            [10, 11, 12, 13],
            [12],
            None,
            2,
        ),
        (
            "compound_interest",
            {
                "principal": 1000,
                "rate_percent": 10,
                "periods": 2,
                "requested": "amount",
            },
            ["১১০০", "১২০০", "১২১০", "১২২০"],
            [1100, 1200, 1210, 1220],
            [1210],
            ["currency"] * 4,
            2,
        ),
    ],
)
def test_additional_competitive_exam_math_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    option_values: list,
    trace: list,
    units: list[str] | None,
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": option_values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }
    if units is not None:
        candidate["deterministic_proof"]["option_units"] = units

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "option_values", "trace", "units", "correct"),
    [
        (
            "direct_proportion",
            {"known_quantity": 5, "known_value": 60, "target_quantity": 8},
            ["৮৪", "৯০", "৯৬", "১০০"],
            [84, 90, 96, 100],
            [12, 96],
            None,
            2,
        ),
        (
            "weighted_average",
            {"values": [10, 20], "weights": [1, 3]},
            ["১৫", "১৭.৫", "২০", "২৫"],
            [15, "17.5", 20, 25],
            [70, 4, "17.5"],
            None,
            1,
        ),
        (
            "partnership_share",
            {
                "capitals": [1000, 2000],
                "durations": [12, 6],
                "total_profit": 600,
                "requested_index": 0,
            },
            ["২০০", "২৫০", "৩০০", "৪০০"],
            [200, 250, 300, 400],
            [24000, 300],
            ["currency"] * 4,
            2,
        ),
    ],
)
def test_more_competitive_exam_math_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    option_values: list,
    trace: list,
    units: list[str] | None,
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": option_values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }
    if units is not None:
        candidate["deterministic_proof"]["option_units"] = units

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters"),
    [
        ("direct_proportion", {"known_quantity": 0, "known_value": 10, "target_quantity": 2}),
        ("weighted_average", {"values": [10, 20], "weights": [1]}),
        (
            "partnership_share",
            {"capitals": [100, 200], "durations": [12, 0], "total_profit": 30, "requested_index": 0},
        ),
    ],
)
def test_more_math_families_reject_invalid_parameters(family: str, parameters: dict) -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": [10, 20, 25, 30],
        "explanation_values": [25],
        "explanation_conclusion": "২৫",
    }

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "math_proof_invalid"


@pytest.mark.parametrize(
    ("family", "parameters", "options", "option_values", "trace", "units", "correct"),
    [
        (
            "percentage_change",
            {"original": 80, "updated": 100},
            ["২০%", "২৫%", "৩০%", "৩৫%"],
            [20, 25, 30, 35],
            [20, 25],
            ["percent"] * 4,
            1,
        ),
        (
            "simple_probability",
            {"favorable": 2, "total": 6},
            ["১/৬", "১/৩", "১/২", "২/৩"],
            ["1/6", "1/3", "1/2", "2/3"],
            ["1/3"],
            ["probability"] * 4,
            1,
        ),
        (
            "rectangle_measure",
            {"length": 12, "width": 5, "requested": "perimeter", "length_unit": "metre"},
            ["২৪", "৩০", "৩৪", "৬০"],
            [24, 30, 34, 60],
            [17, 34],
            ["metre"] * 4,
            2,
        ),
        (
            "discount_price",
            {"marked_price": 800, "discount_percent": 15, "requested": "sale_price"},
            ["১২০", "৬৮০", "৭২০", "৮০০"],
            [120, 680, 720, 800],
            [120, 680],
            ["currency"] * 4,
            1,
        ),
        (
            "simultaneous_linear_equations",
            {"a1": 1, "b1": 1, "c1": 7, "a2": 1, "b2": -1, "c2": 1, "requested": "x"},
            [2, 3, 4, 5],
            [2, 3, 4, 5],
            [-2, -8, 4],
            [""] * 4,
            2,
        ),
        (
            "triangle_measure",
            {"base": 12, "height": 5, "requested": "area", "length_unit": "metre"},
            ["২৫", "৩০", "৩৪", "৬০"],
            [25, 30, 34, 60],
            [60, 30],
            ["square_metre"] * 4,
            1,
        ),
    ],
)
def test_broader_competitive_exam_math_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    option_values: list,
    trace: list,
    units: list[str],
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": option_values,
        "option_units": units,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }
    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "values", "trace", "correct"),
    [
        (
            "permutation_combination",
            {"n": 8, "r": 2, "requested": "combination"},
            ["১৬", "২৮", "৫৬", "৬৪"],
            [16, 28, 56, 64],
            [28],
            1,
        ),
        (
            "inverse_proportion",
            {"known_quantity": 6, "known_value": 15, "target_quantity": 10},
            ["৬", "৯", "১০", "২৫"],
            [6, 9, 10, 25],
            [90, 9],
            1,
        ),
        (
            "quadratic_equation_root",
            {"a": 1, "b": -5, "c": 6, "requested": "larger"},
            ["১", "২", "৩", "৬"],
            [1, 2, 3, 6],
            [1, 1, 3],
            2,
        ),
    ],
)
def test_combinatorics_and_inverse_proportion_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    values: list,
    trace: list,
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }
    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters"),
    [
        ("percentage_change", {"original": 0, "updated": 10}),
        ("simple_probability", {"favorable": 7, "total": 6}),
        (
            "rectangle_measure",
            {"length": 12, "width": -1, "requested": "area", "length_unit": "metre"},
        ),
        ("discount_price", {"marked_price": 100, "discount_percent": 101, "requested": "sale_price"}),
        (
            "simultaneous_linear_equations",
            {"a1": 1, "b1": 1, "c1": 2, "a2": 2, "b2": 2, "c2": 4, "requested": "x"},
        ),
        (
            "triangle_measure",
            {"sides": [1, 2, 3], "requested": "perimeter", "length_unit": "metre"},
        ),
        ("permutation_combination", {"n": 5, "r": 6, "requested": "combination"}),
        (
            "inverse_proportion",
            {"known_quantity": 6, "known_value": 15, "target_quantity": 0},
        ),
        (
            "quadratic_equation_root",
            {"a": 1, "b": 0, "c": 1, "requested": "larger"},
        ),
        (
            "quadratic_equation_root",
            {"a": 1, "b": -2, "c": 1, "requested": "larger"},
        ),
    ],
)
def test_broader_math_families_reject_invalid_parameters(family: str, parameters: dict) -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": [10, 20, 25, 30],
        "option_units": ["percent"] * 4,
        "explanation_values": [25],
        "explanation_conclusion": "২৫",
    }
    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)
    assert raised.value.code == "math_proof_invalid"


def test_exact_square_root_rejects_non_perfect_square() -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": "exact_square_root",
        "parameters": {"radicand": 145},
        "option_values": [10, 11, 12, 13],
        "explanation_values": [12],
        "explanation_conclusion": "১২",
    }

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "math_proof_invalid"


@pytest.mark.parametrize(
    ("family", "parameters", "option_values", "explanation_values", "units", "correct"),
    [
        ("time_work", {"worker_times": [6, 3], "time_unit": "hour"}, [1, 2, 3, 4], ["1/2", 2], ["hour"] * 4, 1),
        (
            "speed_distance",
            {"speed": 60, "time": 2, "requested": "distance", "distance_unit": "kilometre", "time_unit": "hour"},
            [100, 110, 120, 130],
            [120],
            ["kilometre"] * 4,
            2,
        ),
    ],
)
def test_mathematics_units_are_proved_for_every_option(
    family: str,
    parameters: dict,
    option_values: list,
    explanation_values: list,
    units: list[str],
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = ["১০০", "১১০", "১২০", "১৩০"] if family == "speed_distance" else ["১", "২", "৩", "৪"]
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": option_values,
        "option_units": units,
        "explanation_values": explanation_values,
        "explanation_conclusion": candidate["options"][correct],
    }

    assert verify_candidate(candidate).checks["units_match"] is True
    candidate["deterministic_proof"]["option_units"][0] = "minute"
    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)
    assert raised.value.code == "units_inconsistent"


def test_mathematics_explanation_trace_must_match_solver() -> None:
    candidate = mathematics_candidate()
    candidate["deterministic_proof"]["explanation_values"] = [30]

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "explanation_steps_invalid"


@pytest.mark.parametrize(
    ("family", "parameters", "options", "option_values", "trace", "correct"),
    [
        (
            "coding_shift",
            {"source": "CAT", "shift": 1, "direction": "encode"},
            ["DBT", "DBU", "DCU", "EBU"],
            ["DBT", "DBU", "DCU", "EBU"],
            ["DBU"],
            1,
        ),
        (
            "direction_path",
            {"moves": [{"direction": "N", "distance": 3}, {"direction": "E", "distance": 4}]},
            ["উত্তর", "দক্ষিণ", "উত্তর-পূর্ব", "পশ্চিম"],
            ["N", "S", "NE", "W"],
            [4, 3, "NE"],
            2,
        ),
        (
            "ordering_constraints",
            {
                "items": ["A", "B", "C"],
                "constraints": [{"before": "A", "after": "B"}, {"before": "B", "after": "C"}],
                "target": "B",
            },
            [1, 2, 3, 4],
            [1, 2, 3, 4],
            [1, 2],
            1,
        ),
        (
            "syllogism_finite_sets",
            {"sets": {"A": ["1", "2"], "B": ["1", "2", "3"]}, "left": "A", "right": "B", "relation": "all"},
            ["মিথ্যা", "সত্য", "অনির্ণীত", "উভয়"],
            [False, True, "unknown", "both"],
            [True],
            1,
        ),
        (
            "analogy_mapping",
            {"mapping": {"bird": "nest", "bee": "hive"}, "query": "bee"},
            ["den", "hive", "web", "stable"],
            ["den", "hive", "web", "stable"],
            ["hive"],
            1,
        ),
    ],
)
def test_typed_reasoning_families_are_machine_solved(
    family: str,
    parameters: dict,
    options: list[str | int],
    option_values: list,
    trace: list,
    correct: int,
) -> None:
    candidate = reasoning_candidate()
    candidate["options"] = [str(value) for value in options]
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": option_values,
        "explanation_values": trace,
        "explanation_conclusion": candidate["options"][correct],
    }

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "values", "trace", "units", "correct"),
    [
        (
            "calendar_weekday_offset",
            {"start_weekday": 0, "day_offset": 10},
            ["১", "২", "৩", "৪"],
            [1, 2, 3, 4],
            [3],
            None,
            2,
        ),
        (
            "clock_smaller_angle",
            {"hour": 3, "minute": 30},
            ["৬০°", "৭৫°", "৯০°", "১০৫°"],
            [60, 75, 90, 105],
            [75, 75],
            ["degree"] * 4,
            1,
        ),
        (
            "geometric_series_next",
            {"sequence": [2, 6, 18, 54]},
            ["৮১", "১০৮", "১৬২", "২১৬"],
            [81, 108, 162, 216],
            [3, 162],
            None,
            2,
        ),
        (
            "alphabet_series_next",
            {"positions": [23, 26, 3, 6]},
            ["৬", "৭", "৮", "৯"],
            [6, 7, 8, 9],
            [3, 9],
            None,
            3,
        ),
    ],
)
def test_calendar_and_clock_reasoning_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    values: list,
    trace: list,
    units: list[str] | None,
    correct: int,
) -> None:
    candidate = reasoning_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }
    if units is not None:
        candidate["deterministic_proof"]["option_units"] = units
    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "sequence", "options", "values", "trace", "correct"),
    [
        (
            "quadratic_series_next",
            [2, 6, 12, 20],
            [28, 30, 32, 36],
            [28, 30, 32, 36],
            [2, 10, 30],
            1,
        ),
        (
            "alternating_arithmetic_series_next",
            [2, 10, 5, 15, 8, 20],
            [10, 11, 23, 25],
            [10, 11, 23, 25],
            [3, 5, 11],
            1,
        ),
    ],
)
def test_additional_series_families_are_solved(
    family: str,
    sequence: list[int],
    options: list[int],
    values: list[int],
    trace: list[int],
    correct: int,
) -> None:
    candidate = reasoning_candidate()
    candidate["options"] = [str(value) for value in options]
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": {"sequence": sequence},
        "option_values": values,
        "explanation_values": trace,
        "explanation_conclusion": str(options[correct]),
    }
    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters"),
    [
        ("calendar_weekday_offset", {"start_weekday": 7, "day_offset": 1}),
        ("calendar_weekday_offset", {"start_weekday": 0, "day_offset": -1}),
        ("clock_smaller_angle", {"hour": 24, "minute": 0}),
        ("clock_smaller_angle", {"hour": 3, "minute": 60}),
        ("geometric_series_next", {"sequence": [2, 6, 17]}),
        ("geometric_series_next", {"sequence": [0, 0, 0]}),
        ("alphabet_series_next", {"positions": [1, 3, 6]}),
        ("alphabet_series_next", {"positions": [0, 3, 6]}),
        ("quadratic_series_next", {"sequence": [1, 4, 9, 17]}),
        ("quadratic_series_next", {"sequence": [2, 5, 8, 11]}),
        ("alternating_arithmetic_series_next", {"sequence": [1, 2, 3, 4, 6, 8]}),
        ("alternating_arithmetic_series_next", {"sequence": [1, 1, 1, 1, 1, 1]}),
    ],
)
def test_calendar_and_clock_reasoning_reject_invalid_parameters(family: str, parameters: dict) -> None:
    candidate = reasoning_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": [1, 2, 3, 4],
        "explanation_values": [3],
        "explanation_conclusion": "৩",
    }
    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)
    assert raised.value.code == "reasoning_proof_invalid"


def test_underconstrained_ordering_is_rejected() -> None:
    candidate = reasoning_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": "ordering_constraints",
        "parameters": {
            "items": ["A", "B", "C"],
            "constraints": [{"before": "A", "after": "B"}],
            "target": "B",
        },
        "option_values": [1, 2, 3, 4],
        "explanation_values": [3, 2],
        "explanation_conclusion": "২",
    }

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "reasoning_proof_invalid"


def language_candidate(subject: str) -> dict:
    candidate = evidence_candidate()
    candidate["subject_key"] = subject
    candidate["language"] = "bn-en" if subject == "english" else "bn"
    candidate["language_question_form"] = "grammar_rule"
    candidate["language_verification"] = {
        "version": 1,
        "authority_type": "reviewed_reference",
        "rule_id": "rule-001",
        "source_span": "পশ্চিমবঙ্গের রাজধানী কলকাতা",
        "review_status": "human_reviewed" if subject == "english" else "source_proved",
        "uncertain": False,
        "translation_status": "human_reviewed",
    }
    if subject == "english":
        candidate["language_human_review"] = {
            "reviewer_id": "operator-1",
            "reviewed_at": "2026-08-08T10:00:00+00:00",
            "decision": "approved",
        }
    return candidate


def test_english_language_form_requires_versioned_source_rule() -> None:
    candidate = language_candidate("english")
    candidate["language_verification"]["review_status"] = "source_proved"
    candidate["language_verification"]["translation_status"] = "not_applicable"
    candidate.pop("language_human_review")

    result = verify_candidate(candidate)

    assert result.language_form == "grammar_rule"
    assert result.as_dict()["language_form"] == "grammar_rule"


def test_uncertain_bengali_routes_to_human_review() -> None:
    candidate = language_candidate("bengali")
    candidate["language_verification"]["uncertain"] = True

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "language_review_required"
    candidate["language_verification"]["review_status"] = "human_reviewed"
    candidate["language_human_review"] = {
        "reviewer_id": "operator-1",
        "reviewed_at": "2026-08-08T10:00:00+00:00",
        "decision": "approved",
    }
    assert verify_candidate(candidate).language_form == "grammar_rule"


def test_uncertain_english_routes_to_human_review() -> None:
    candidate = language_candidate("english")
    candidate["language_verification"].update(
        review_status="source_proved",
        translation_status="not_applicable",
        uncertain=True,
    )
    candidate.pop("language_human_review")

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "language_review_required"


def test_language_verification_requires_explicit_uncertainty() -> None:
    candidate = language_candidate("english")
    candidate["language_verification"].pop("uncertain")

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "language_uncertainty_invalid"


def test_translation_correctness_is_separate_from_factual_proof() -> None:
    candidate = language_candidate("bengali")
    candidate["language_question_form"] = "translation"
    candidate["language_verification"]["translation_status"] = "source_proved"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "translation_review_required"


def test_model_declared_human_review_is_not_an_attestation() -> None:
    candidate = language_candidate("bengali")
    candidate["language_verification"]["uncertain"] = True
    candidate["language_verification"]["review_status"] = "human_reviewed"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "language_review_required"


def test_language_rule_span_must_be_present_in_authoritative_evidence() -> None:
    candidate = language_candidate("english")
    candidate["language_verification"]["source_span"] = "উৎসে নেই"

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == "language_evidence_invalid"


def test_duplicate_current_affairs_event_is_rejected_by_knowledge_point(
    valid_questions,
) -> None:
    first = deepcopy(valid_questions[0])
    second = deepcopy(valid_questions[1])
    for row in (first, second):
        row.update(
            {
                "subject_key": "current-affairs",
                "chapter": "জাতীয় সাম্প্রতিক ঘটনা",
                "canonical_claim": "একই দপ্তরে একই ব্যক্তির নিয়োগ",
                "knowledge_entity": "office-x",
                "knowledge_relation": "appointed_person",
                "knowledge_answer_value": "person-y",
                "knowledge_time_scope": "2026-08",
            }
        )

    accepted, rejected = validate_question_candidates(
        [first, second],
        "current-affairs",
        "জাতীয় সাম্প্রতিক ঘটনা",
    )

    assert len(accepted) == 1
    assert rejected == [
        {
            "index": 1,
            "code": "duplicate_knowledge_point",
            "message": "Candidate duplicates a knowledge point already accepted in this batch.",
        }
    ]


@pytest.mark.parametrize(
    ("family", "parameters", "options", "values", "trace", "units", "correct"),
    [
        (
            "age_ratio",
            {
                "older_ratio": 5,
                "younger_ratio": 3,
                "age_difference": 12,
                "years_offset": 4,
                "requested": "younger_present",
            },
            ["১২", "১৪", "১৬", "১৮"],
            [12, 14, 16, 18],
            [6, 18, 14],
            ["year"] * 4,
            1,
        ),
        (
            "boat_stream",
            {
                "boat_speed": 10,
                "stream_speed": 2,
                "distance": 24,
                "requested": "upstream_time",
                "speed_unit": "kilometre/hour",
                "distance_unit": "kilometre",
            },
            ["২", "৩", "৪", "৬"],
            [2, 3, 4, 6],
            [8, 3],
            ["hour"] * 4,
            1,
        ),
        (
            "circle_measure",
            {
                "radius": 7,
                "pi_numerator": 22,
                "pi_denominator": 7,
                "requested": "area",
                "length_unit": "centimetre",
            },
            ["১৪৪", "১৫৪", "১৬৪", "১৭৬"],
            [144, 154, 164, 176],
            [154],
            ["square_centimetre"] * 4,
            1,
        ),
    ],
)
def test_syllabus_gap_mathematics_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    values: list,
    trace: list,
    units: list[str],
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": values,
        "option_units": units,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "values", "trace", "correct"),
    [
        (
            "two_set_cardinality",
            {
                "first_count": 30,
                "second_count": 25,
                "intersection": 10,
                "total_population": 60,
                "requested": "neither",
            },
            ["৫", "১০", "১৫", "২০"],
            [5, 10, 15, 20],
            [45, 15],
            2,
        ),
        (
            "bidirectional_rank_total",
            {"rank_from_left": 12, "rank_from_right": 9},
            ["১৮", "১৯", "২০", "২১"],
            [18, 19, 20, 21],
            [20],
            2,
        ),
        (
            "clock_mirror_time",
            {"hour": 3, "minute": 25},
            ["08:25", "08:30", "08:35", "09:35"],
            ["08:25", "08:30", "08:35", "09:35"],
            ["08:35"],
            2,
        ),
    ],
)
def test_syllabus_gap_reasoning_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    values: list,
    trace: list,
    correct: int,
) -> None:
    candidate = reasoning_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "values", "trace", "units", "correct"),
    [
        (
            "mixture_replacement",
            {
                "total_volume": 100,
                "removed_volume": 20,
                "initial_concentration_percent": 100,
                "replacement_concentration_percent": 0,
                "repetitions": 2,
            },
            ["৬০%", "৬৪%", "৬৮%", "৮০%"],
            [60, 64, 68, 80],
            ["0.8", 64],
            ["percent"] * 4,
            1,
        ),
        (
            "mean_median_mode",
            {"values": [2, 4, 8, 10], "requested": "median"},
            ["৫", "৬", "৭", "৮"],
            [5, 6, 7, 8],
            [6],
            None,
            1,
        ),
        (
            "mean_median_mode",
            {"values": [2, 4, 6], "requested": "mean"},
            ["৩", "৪", "৫", "৬"],
            [3, 4, 5, 6],
            [12, 4],
            None,
            1,
        ),
        (
            "mean_median_mode",
            {"values": [1, 2, 2, 3], "requested": "mode"},
            ["১", "২", "৩", "৪"],
            [1, 2, 3, 4],
            [2],
            None,
            1,
        ),
        (
            "train_crossing",
            {
                "train_length": 120,
                "object_length": 180,
                "speed": 54,
                "speed_unit": "kilometre/hour",
                "length_unit": "metre",
            },
            ["১৫", "১৮", "২০", "২৪"],
            [15, 18, 20, 24],
            [15, 300, 20],
            ["second"] * 4,
            2,
        ),
        (
            "train_crossing",
            {
                "train_length": 100,
                "object_length": 50,
                "speed": 10,
                "speed_unit": "metre/second",
                "length_unit": "metre",
            },
            ["১০", "১২", "১৫", "২০"],
            [10, 12, 15, 20],
            [10, 150, 15],
            ["second"] * 4,
            2,
        ),
        (
            "solid_measure",
            {
                "shape": "cylinder",
                "radius": 7,
                "height": 10,
                "pi_numerator": 22,
                "pi_denominator": 7,
                "length_unit": "centimetre",
                "requested": "volume",
            },
            ["১৪৪০", "১৫৪০", "১৬৪০", "১৭৬০"],
            [1440, 1540, 1640, 1760],
            [1540],
            ["cubic_centimetre"] * 4,
            1,
        ),
        (
            "solid_measure",
            {
                "shape": "cuboid",
                "length": 2,
                "width": 3,
                "height": 4,
                "length_unit": "metre",
                "requested": "total_surface_area",
            },
            ["৪৮", "৫০", "৫২", "৫৪"],
            [48, 50, 52, 54],
            [52],
            ["square_metre"] * 4,
            2,
        ),
        (
            "solid_measure",
            {
                "shape": "cylinder",
                "radius": 7,
                "height": 3,
                "pi_numerator": 22,
                "pi_denominator": 7,
                "length_unit": "centimetre",
                "requested": "total_surface_area",
            },
            ["৪০০", "৪২০", "৪৪০", "৪৬০"],
            [400, 420, 440, 460],
            [440],
            ["square_centimetre"] * 4,
            2,
        ),
    ],
)
def test_additional_syllabus_mathematics_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    values: list,
    trace: list,
    units: list[str] | None,
    correct: int,
) -> None:
    candidate = mathematics_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }
    if units is not None:
        candidate["deterministic_proof"]["option_units"] = units

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("family", "parameters", "options", "values", "trace", "correct"),
    [
        (
            "three_set_cardinality",
            {
                "first_count": 30,
                "second_count": 25,
                "third_count": 20,
                "first_second_intersection": 10,
                "first_third_intersection": 5,
                "second_third_intersection": 4,
                "all_three_intersection": 3,
                "requested": "exactly_one",
            },
            ["৪২", "৪৪", "৪৬", "৪৮"],
            [42, 44, 46, 48],
            [59, 46],
            2,
        ),
        (
            "family_tree_relation",
            {
                "people": {"A": "male", "B": "female", "C": "male"},
                "parent_edges": [
                    {"parent": "A", "child": "C"},
                    {"parent": "B", "child": "C"},
                ],
                "subject": "A",
                "reference": "C",
            },
            ["mother", "father", "brother", "uncle"],
            ["mother", "father", "brother", "uncle"],
            ["father"],
            1,
        ),
        (
            "family_tree_relation",
            {
                "people": {"G": "female", "P": "male", "C": "female"},
                "parent_edges": [
                    {"parent": "G", "child": "P"},
                    {"parent": "P", "child": "C"},
                ],
                "subject": "G",
                "reference": "C",
            },
            ["mother", "grandmother", "aunt", "sister"],
            ["mother", "grandmother", "aunt", "sister"],
            ["grandmother"],
            1,
        ),
        (
            "family_tree_relation",
            {
                "people": {"G": "female", "U": "male", "P": "female", "C": "male"},
                "parent_edges": [
                    {"parent": "G", "child": "U"},
                    {"parent": "G", "child": "P"},
                    {"parent": "P", "child": "C"},
                ],
                "subject": "U",
                "reference": "C",
            },
            ["father", "brother", "uncle", "grandfather"],
            ["father", "brother", "uncle", "grandfather"],
            ["uncle"],
            2,
        ),
        (
            "circular_seating_constraints",
            {
                "items": ["A", "B", "C", "D"],
                "anchor": "A",
                "direction": "clockwise",
                "query_steps": 2,
                "constraints": [
                    {"type": "clockwise_adjacent", "first": "A", "second": "B"},
                    {"type": "clockwise_adjacent", "first": "B", "second": "C"},
                    {"type": "clockwise_adjacent", "first": "C", "second": "D"},
                ],
            },
            ["A", "B", "C", "D"],
            ["A", "B", "C", "D"],
            [1, "C"],
            2,
        ),
        (
            "circular_seating_constraints",
            {
                "items": ["A", "B", "C", "D", "E", "F"],
                "anchor": "A",
                "direction": "counterclockwise",
                "query_steps": 1,
                "constraints": [
                    {"type": "clockwise_adjacent", "first": "A", "second": "B"},
                    {"type": "clockwise_adjacent", "first": "B", "second": "C"},
                    {"type": "opposite", "first": "A", "second": "D"},
                    {"type": "clockwise_steps", "first": "B", "second": "E", "steps": 3},
                    {"type": "clockwise_adjacent", "first": "E", "second": "F"},
                ],
            },
            ["C", "D", "E", "F"],
            ["C", "D", "E", "F"],
            [1, "F"],
            3,
        ),
    ],
)
def test_additional_syllabus_reasoning_families_are_solved(
    family: str,
    parameters: dict,
    options: list[str],
    values: list,
    trace: list,
    correct: int,
) -> None:
    candidate = reasoning_candidate()
    candidate["options"] = options
    candidate["correct_index"] = correct
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": values,
        "explanation_values": trace,
        "explanation_conclusion": options[correct],
    }

    assert verify_candidate(candidate).family == family


@pytest.mark.parametrize(
    ("subject", "family", "parameters", "expected_code"),
    [
        (
            "mathematics",
            "age_ratio",
            {
                "older_ratio": 3,
                "younger_ratio": 3,
                "age_difference": 10,
                "years_offset": 0,
                "requested": "older_present",
            },
            "math_proof_invalid",
        ),
        (
            "mathematics",
            "boat_stream",
            {
                "boat_speed": 5,
                "stream_speed": 5,
                "distance": 10,
                "requested": "upstream_time",
                "speed_unit": "kilometre/hour",
                "distance_unit": "kilometre",
            },
            "math_proof_invalid",
        ),
        (
            "mathematics",
            "circle_measure",
            {"radius": 7, "pi_numerator": 4, "pi_denominator": 1, "requested": "area", "length_unit": "metre"},
            "math_proof_invalid",
        ),
        (
            "reasoning",
            "two_set_cardinality",
            {"first_count": 3, "second_count": 4, "intersection": 5, "requested": "union"},
            "reasoning_proof_invalid",
        ),
        (
            "reasoning",
            "bidirectional_rank_total",
            {"rank_from_left": 0, "rank_from_right": 4},
            "reasoning_proof_invalid",
        ),
        (
            "reasoning",
            "clock_mirror_time",
            {"hour": 13, "minute": 0},
            "reasoning_proof_invalid",
        ),
        (
            "mathematics",
            "mixture_replacement",
            {"total_volume": 10, "removed_volume": 11, "initial_concentration_percent": 50, "replacement_concentration_percent": 0, "repetitions": 1},
            "math_proof_invalid",
        ),
        (
            "mathematics",
            "mean_median_mode",
            {"values": [1, 1, 2, 2], "requested": "mode"},
            "math_proof_invalid",
        ),
        (
            "mathematics",
            "train_crossing",
            {"train_length": 100, "object_length": -1, "speed": 50, "speed_unit": "kilometre/hour", "length_unit": "metre"},
            "math_proof_invalid",
        ),
        (
            "mathematics",
            "solid_measure",
            {"shape": "cylinder", "radius": 7, "height": 10, "pi_numerator": 4, "pi_denominator": 1, "length_unit": "metre", "requested": "volume"},
            "math_proof_invalid",
        ),
        (
            "reasoning",
            "three_set_cardinality",
            {"first_count": 2, "second_count": 3, "third_count": 4, "first_second_intersection": 3, "first_third_intersection": 0, "second_third_intersection": 0, "all_three_intersection": 0, "requested": "union"},
            "reasoning_proof_invalid",
        ),
        (
            "reasoning",
            "family_tree_relation",
            {"people": {"A": "male", "B": "female"}, "parent_edges": [{"parent": "A", "child": "B"}, {"parent": "B", "child": "A"}], "subject": "A", "reference": "B"},
            "reasoning_proof_invalid",
        ),
        (
            "reasoning",
            "circular_seating_constraints",
            {"items": ["A", "B", "C", "D"], "anchor": "A", "direction": "clockwise", "query_steps": 2, "constraints": [{"type": "adjacent", "first": "A", "second": "B"}]},
            "reasoning_proof_invalid",
        ),
        (
            "mathematics",
            "percentage_of",
            {"base": "1e1000000", "percent": 10},
            "math_proof_invalid",
        ),
        (
            "mathematics",
            "rounded_division",
            {"numerator": "1e-1000000", "denominator": 2, "decimal_places": 2, "rounding_mode": "half_up"},
            "math_proof_invalid",
        ),
    ],
)
def test_syllabus_gap_families_fail_closed_on_invalid_parameters(
    subject: str,
    family: str,
    parameters: dict,
    expected_code: str,
) -> None:
    candidate = mathematics_candidate() if subject == "mathematics" else reasoning_candidate()
    candidate["deterministic_proof"] = {
        "version": 1,
        "family": family,
        "parameters": parameters,
        "option_values": [1, 2, 3, 4],
        "explanation_values": [1],
        "explanation_conclusion": candidate["options"][candidate["correct_index"]],
    }

    with pytest.raises(DeterministicVerificationError) as raised:
        verify_candidate(candidate)

    assert raised.value.code == expected_code
