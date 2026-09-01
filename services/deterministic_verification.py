"""Deterministic candidate verification for evidence, maths, and reasoning.

The payload consumed here is deliberately small and versioned.  It contains
machine-readable inputs, never a claimed answer.  The verifier computes the
answer, proves that exactly one displayed option matches, and checks that the
explanation concludes with that answer.  Unsupported families fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from itertools import permutations, product
from math import comb, gcd, isqrt, perm
from typing import Any, Mapping, Sequence

from config.settings import DETERMINISTIC_PROOF_VERSION
from utils.hashing import normalize_text

PROOF_VERSION = DETERMINISTIC_PROOF_VERSION
_BENGALI_RE = re.compile(r"[\u0980-\u09ff]")
_MOJIBAKE = ("ï¿½", "à¦", "à§", "�")


class DeterministicVerificationError(ValueError):
    """A stable rejection reason produced without a model call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DeterministicResult:
    version: int
    family: str
    expected_answer: str | None
    checks: dict[str, bool]
    language_form: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "family": self.family,
            "expected_answer": self.expected_answer,
            "checks": dict(self.checks),
            "language_form": self.language_form,
        }


@dataclass(frozen=True, slots=True)
class _SolvedValue:
    value: Any
    explanation_values: tuple[Any, ...]
    unit: str | None = None


def verify_candidate(
    candidate: Mapping[str, Any],
    *,
    now: datetime | None = None,
    require_subject_proof: bool = True,
) -> DeterministicResult:
    """Run common checks and, where required, solve the candidate exactly."""
    subject = str(candidate.get("subject_key") or candidate.get("subject") or "").strip()
    options = candidate.get("options")
    correct_index = candidate.get("correct_index")
    if not isinstance(options, list) or len(options) != 4:
        raise DeterministicVerificationError("options_invalid", "Deterministic verification requires four options.")
    if isinstance(correct_index, bool) or not isinstance(correct_index, int) or correct_index not in range(4):
        raise DeterministicVerificationError(
            "answer_invalid", "Deterministic verification requires one declared answer."
        )

    option_pattern_safe = _verify_option_quality(
        options,
        correct_index,
        enforce_pattern=require_subject_proof,
    )
    _verify_language(candidate, subject)
    _verify_source_dates(candidate, now=now)
    language_form = _verify_subject_language_contract(
        candidate,
        subject,
        required=require_subject_proof,
    )

    proof = candidate.get("deterministic_proof")
    if proof is None:
        if require_subject_proof:
            raise DeterministicVerificationError(
                "proof_missing",
                f"{subject or 'new inventory'} candidates require a machine-checkable proof payload.",
            )
        return DeterministicResult(
            version=PROOF_VERSION,
            family="common",
            expected_answer=None,
            checks={
                "options_materially_distinct": True,
                "option_pattern_safe": option_pattern_safe,
                "language_valid": True,
                "source_dates_valid": True,
                "unique_answer_proved": False,
            },
            language_form=language_form,
        )
    if not isinstance(proof, Mapping) or proof.get("version") != PROOF_VERSION:
        raise DeterministicVerificationError(
            "proof_invalid", "The deterministic proof version is missing or unsupported."
        )

    family = str(proof.get("family") or "").strip()
    solved: _SolvedValue
    if family == "evidence_single_answer":
        solved = _SolvedValue(_solve_evidence(candidate, proof), ())
    elif family == "evidence_span_single_answer":
        solved = _SolvedValue(_solve_evidence_span(candidate, proof), ())
    elif subject == "mathematics":
        solved = _solve_mathematics(family, proof.get("parameters"))
    elif subject == "reasoning":
        solved = _solve_reasoning(family, proof.get("parameters"))
    else:
        raise DeterministicVerificationError(
            "proof_family_unsupported",
            f"Unsupported deterministic proof family: {family or 'blank'}.",
        )

    option_values = proof.get("option_values")
    if not isinstance(option_values, Sequence) or isinstance(option_values, (str, bytes)) or len(option_values) != 4:
        raise DeterministicVerificationError(
            "proof_invalid", "The proof must provide four machine-readable option values."
        )
    matches = [index for index, value in enumerate(option_values) if _values_equal(value, solved.value)]
    if len(matches) != 1:
        raise DeterministicVerificationError(
            "answer_not_unique",
            "The deterministic solver did not find exactly one defensible option.",
        )
    if matches[0] != correct_index:
        raise DeterministicVerificationError(
            "declared_answer_wrong",
            "The declared answer disagrees with the deterministic solver.",
        )

    if subject in {"mathematics", "reasoning"} and family not in {
        "evidence_single_answer",
        "evidence_span_single_answer",
    }:
        _verify_explanation_values(proof, solved.explanation_values)
    if solved.unit is not None:
        _verify_option_units(proof, solved.unit)

    expected_text = str(options[correct_index]).strip()
    conclusion = str(proof.get("explanation_conclusion") or "").strip()
    if not conclusion or normalize_text(conclusion) != normalize_text(expected_text):
        raise DeterministicVerificationError(
            "explanation_contradiction",
            "The explanation conclusion does not match the proved answer.",
        )
    return DeterministicResult(
        version=PROOF_VERSION,
        family=family,
        expected_answer=expected_text,
        checks={
            "options_materially_distinct": True,
            "option_pattern_safe": option_pattern_safe,
            "language_valid": True,
            "source_dates_valid": True,
            "solver_supported": True,
            "unique_answer_proved": True,
            "declared_answer_matches": True,
            "explanation_steps_match": True,
            "units_match": True,
            "explanation_matches": True,
        },
        language_form=language_form,
    )


def _verify_option_quality(
    options: Sequence[Any],
    correct_index: int,
    *,
    enforce_pattern: bool,
) -> bool:
    material = [_material_option(value) for value in options]
    if any(not value for value in material) or len(set(material)) != 4:
        raise DeterministicVerificationError(
            "options_materially_duplicate",
            "Options are not materially distinct after labels and punctuation are removed.",
        )
    kinds = [_option_kind(value) for value in options]
    correct_kind = kinds[correct_index]
    pattern_safe = not (kinds.count(correct_kind) == 1 and len(set(kinds)) > 1)
    if not pattern_safe and enforce_pattern:
        raise DeterministicVerificationError(
            "option_pattern_leakage",
            "The correct option is the only option with its visible value pattern.",
        )
    return pattern_safe


def _material_option(value: Any) -> str:
    text = normalize_text(str(value))
    text = re.sub(r"^(?:option|বিকল্প)?\s*[a-dক-ঘ১-৪1-4][\s:.)-]+", "", text)
    return re.sub(r"[^\w\u0980-\u09ff]+", "", text)


def _option_kind(value: Any) -> str:
    text = str(value).strip().replace(",", "")
    try:
        Decimal(text)
        return "number"
    except InvalidOperation:
        pass
    has_bn = bool(_BENGALI_RE.search(text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_bn and has_latin:
        return "mixed_script"
    if has_bn:
        return "bengali"
    if has_latin:
        return "latin"
    return "symbol"


def _verify_language(candidate: Mapping[str, Any], subject: str) -> None:
    question = str(candidate.get("question") or candidate.get("question_text") or "")
    explanation = " ".join(str(candidate.get(name) or "") for name in ("explanation", "detailed_explanation"))
    combined = question + " " + explanation
    if any(marker in combined for marker in _MOJIBAKE):
        raise DeterministicVerificationError(
            "language_encoding_invalid", "Candidate text contains broken Unicode encoding."
        )
    language = str(candidate.get("language") or ("bn-en" if subject == "english" else "bn")).lower()
    if language in {"bn", "bn-en"} and not _BENGALI_RE.search(combined):
        raise DeterministicVerificationError(
            "language_script_invalid", "Bengali content has no readable Bengali script."
        )
    if language == "en" and _BENGALI_RE.search(question):
        raise DeterministicVerificationError(
            "language_script_invalid", "English-only content contains Bengali question text."
        )
    terminology = candidate.get("terminology_glossary")
    if terminology is not None:
        if not isinstance(terminology, Mapping):
            raise DeterministicVerificationError("terminology_invalid", "Terminology glossary must be an object.")
        for canonical, observed in terminology.items():
            if normalize_text(str(canonical)) != normalize_text(str(observed)):
                raise DeterministicVerificationError(
                    "translation_mismatch",
                    "Candidate terminology disagrees with the reviewed glossary.",
                )


def _verify_subject_language_contract(
    candidate: Mapping[str, Any],
    subject: str,
    *,
    required: bool,
) -> str | None:
    if subject not in {"english", "bengali"}:
        return None
    form = str(candidate.get("language_question_form") or "").strip()
    if not required and not form:
        return None
    allowed = {
        "english": {"grammar_rule", "vocabulary", "comprehension", "error_detection"},
        "bengali": {
            "grammar_rule",
            "vocabulary",
            "comprehension",
            "literature",
            "linguistics",
            "translation",
        },
    }
    if form not in allowed[subject]:
        raise DeterministicVerificationError(
            "language_form_invalid",
            f"{subject} candidates require a supported typed language question form.",
        )
    verification = candidate.get("language_verification")
    if not isinstance(verification, Mapping) or verification.get("version") != 1:
        raise DeterministicVerificationError(
            "language_evidence_missing",
            "Language questions require a versioned authoritative rule artifact.",
        )
    authority = str(verification.get("authority_type") or "")
    rule_id = str(verification.get("rule_id") or "").strip()
    source_span = str(verification.get("source_span") or "").strip()
    evidence = normalize_text(str(candidate.get("evidence_summary") or ""))
    if (
        authority not in {"official", "primary", "reviewed_reference"}
        or not rule_id
        or not source_span
        or normalize_text(source_span) not in evidence
    ):
        raise DeterministicVerificationError(
            "language_evidence_invalid",
            "The language rule is not anchored to the supplied authoritative source span.",
        )
    review_status = str(verification.get("review_status") or "")
    raw_uncertain = verification.get("uncertain")
    if not isinstance(raw_uncertain, bool):
        raise DeterministicVerificationError(
            "language_uncertainty_invalid",
            "Language verification requires an explicit uncertainty decision.",
        )
    uncertain = raw_uncertain
    if review_status not in {"source_proved", "human_reviewed"}:
        raise DeterministicVerificationError(
            "language_review_invalid", "Language review status is missing or unsupported."
        )
    human_reviewed = review_status == "human_reviewed" and _has_human_review_attestation(candidate)
    if review_status == "human_reviewed" and not human_reviewed:
        raise DeterministicVerificationError(
            "language_review_required",
            "A model-declared human review is not an operator attestation.",
        )
    if uncertain and not human_reviewed:
        raise DeterministicVerificationError(
            "language_review_required",
            "Uncertain language content must enter human review.",
        )
    if form == "translation" and (verification.get("translation_status") != "human_reviewed" or not human_reviewed):
        raise DeterministicVerificationError(
            "translation_review_required",
            "Translation correctness requires a separate human-reviewed decision.",
        )
    return form


def _has_human_review_attestation(candidate: Mapping[str, Any]) -> bool:
    attestation = candidate.get("language_human_review")
    if not isinstance(attestation, Mapping):
        return False
    reviewer_id = str(attestation.get("reviewer_id") or "").strip()
    reviewed_at = str(attestation.get("reviewed_at") or "").strip()
    decision = str(attestation.get("decision") or "")
    if not reviewer_id or not reviewed_at or decision != "approved":
        return False
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _verify_source_dates(candidate: Mapping[str, Any], *, now: datetime | None) -> None:
    current = _utc(now or datetime.now(timezone.utc))
    published = _parse_datetime(candidate.get("source_published_at"), "source publication")
    accessed = _parse_datetime(candidate.get("source_accessed_at"), "source access")
    expires = _parse_datetime(
        candidate.get("source_expires_at") or candidate.get("expires_at"),
        "source expiry",
    )
    effective = _parse_datetime(candidate.get("fact_effective_at"), "fact effective")
    if published and accessed and published > accessed:
        raise DeterministicVerificationError(
            "source_date_inconsistent", "Source publication is after its access timestamp."
        )
    if effective and effective > current:
        raise DeterministicVerificationError("fact_not_effective", "The fact is not effective at verification time.")
    if expires and expires < current:
        raise DeterministicVerificationError("source_stale", "The source fact expired before verification.")


def _solve_mathematics(family: str, raw: Any) -> _SolvedValue:
    params = _mapping(raw)
    result: Any
    try:
        if family == "arithmetic_expression":
            values = [_fraction(value) for value in _sequence(params.get("values"))]
            operators = [str(value) for value in _sequence(params.get("operators"))]
            if not values or len(operators) != len(values) - 1:
                raise ValueError
            result = values[0]
            for operator, value in zip(operators, values[1:], strict=True):
                if operator == "+":
                    result += value
                elif operator == "-":
                    result -= value
                elif operator == "*":
                    result *= value
                elif operator == "/" and value:
                    result /= value
                else:
                    raise ValueError
            return _SolvedValue(result, (result,))
        if family == "percentage_of":
            result = _fraction(params["base"]) * _fraction(params["percent"]) / 100
            return _SolvedValue(result, (result,))
        if family == "average":
            values = [_fraction(value) for value in _sequence(params.get("values"))]
            if not values:
                raise ValueError
            total = sum(values, Fraction())
            result = total / len(values)
            return _SolvedValue(result, (total, result))
        if family == "ratio_share":
            left = _fraction(params["left_ratio"])
            right = _fraction(params["right_ratio"])
            total = _fraction(params["total"])
            requested = str(params.get("requested") or "")
            if left <= 0 or right <= 0 or requested not in {"left", "right"}:
                raise ValueError
            result = total * (left if requested == "left" else right) / (left + right)
            return _SolvedValue(result, (left + right, result))
        if family == "simple_interest":
            result = (
                _fraction(params["principal"]) * _fraction(params["rate_percent"]) * _fraction(params["years"]) / 100
            )
            return _SolvedValue(result, (result,))
        if family == "algebra_linear":
            coefficient = _fraction(params["coefficient"])
            constant = _fraction(params["constant"])
            right_hand_side = _fraction(params["right_hand_side"])
            if not coefficient:
                raise ValueError
            remainder = right_hand_side - constant
            result = remainder / coefficient
            return _SolvedValue(result, (remainder, result))
        if family == "time_work":
            worker_times = [_fraction(value) for value in _sequence(params.get("worker_times"))]
            if len(worker_times) not in range(2, 7) or any(value <= 0 for value in worker_times):
                raise ValueError
            combined_rate = sum((Fraction(1, 1) / value for value in worker_times), Fraction())
            result = Fraction(1, 1) / combined_rate
            unit = _required_unit(params.get("time_unit"), {"second", "minute", "hour", "day"})
            return _SolvedValue(result, (combined_rate, result), unit)
        if family == "speed_distance":
            requested = str(params.get("requested") or "")
            distance_unit = _required_unit(params.get("distance_unit"), {"metre", "kilometre"})
            time_unit = _required_unit(params.get("time_unit"), {"second", "minute", "hour"})
            if requested == "distance":
                speed = _fraction(params["speed"])
                duration = _fraction(params["time"])
                if speed <= 0 or duration <= 0:
                    raise ValueError
                result = speed * duration
                return _SolvedValue(result, (result,), distance_unit)
            if requested == "time":
                distance = _fraction(params["distance"])
                speed = _fraction(params["speed"])
                if distance <= 0 or speed <= 0:
                    raise ValueError
                result = distance / speed
                return _SolvedValue(result, (result,), time_unit)
            if requested == "speed":
                distance = _fraction(params["distance"])
                duration = _fraction(params["time"])
                if distance <= 0 or duration <= 0:
                    raise ValueError
                result = distance / duration
                return _SolvedValue(result, (result,), f"{distance_unit}/{time_unit}")
            raise ValueError
        if family == "profit_loss":
            cost = _fraction(params["cost_price"])
            selling = _fraction(params["selling_price"])
            requested = str(params.get("requested") or "")
            if cost <= 0 or selling < 0:
                raise ValueError
            difference = selling - cost
            if requested == "profit_amount" and difference >= 0:
                return _SolvedValue(difference, (difference,), "currency")
            if requested == "loss_amount" and difference <= 0:
                return _SolvedValue(-difference, (-difference,), "currency")
            if requested == "profit_percent" and difference >= 0:
                result = difference * 100 / cost
                return _SolvedValue(result, (difference, result), "percent")
            if requested == "loss_percent" and difference <= 0:
                result = -difference * 100 / cost
                return _SolvedValue(result, (-difference, result), "percent")
            raise ValueError
        if family == "rounded_division":
            numerator = _decimal(params["numerator"])
            denominator = _decimal(params["denominator"])
            places = params.get("decimal_places")
            if denominator == 0 or isinstance(places, bool) or not isinstance(places, int) or places not in range(0, 7):
                raise ValueError
            if str(params.get("rounding_mode") or "") != "half_up":
                raise ValueError
            quantum = Decimal(1).scaleb(-places)
            result = (numerator / denominator).quantize(quantum, rounding=ROUND_HALF_UP)
            return _SolvedValue(result, (result,))
        if family == "gcd_lcm":
            integer_values = [_positive_int(value) for value in _sequence(params.get("values"))]
            requested = str(params.get("requested") or "")
            if len(integer_values) not in range(2, 9):
                raise ValueError
            if requested == "gcd":
                integer_result = integer_values[0]
                for integer_value in integer_values[1:]:
                    integer_result = gcd(integer_result, integer_value)
            elif requested == "lcm":
                integer_result = 1
                for integer_value in integer_values:
                    integer_result = integer_result * integer_value // gcd(integer_result, integer_value)
                    if integer_result > 10**12:
                        raise ValueError
            else:
                raise ValueError
            return _SolvedValue(integer_result, (integer_result,))
        if family == "exact_square_root":
            radicand = _positive_int(params.get("radicand"), maximum=10**12)
            result = isqrt(radicand)
            if result * result != radicand:
                raise ValueError
            return _SolvedValue(result, (result,))
        if family == "compound_interest":
            principal = _fraction(params["principal"])
            rate = _fraction(params["rate_percent"])
            periods = _positive_int(params.get("periods"), maximum=100)
            requested = str(params.get("requested") or "")
            if principal <= 0 or rate <= 0 or rate > 1000:
                raise ValueError
            amount = principal * (Fraction(1) + rate / 100) ** periods
            if requested == "amount":
                return _SolvedValue(amount, (amount,), "currency")
            if requested == "interest":
                result = amount - principal
                return _SolvedValue(result, (amount, result), "currency")
            raise ValueError
        if family == "direct_proportion":
            known_quantity = _fraction(params["known_quantity"])
            known_value = _fraction(params["known_value"])
            target_quantity = _fraction(params["target_quantity"])
            if known_quantity <= 0 or known_value < 0 or target_quantity <= 0:
                raise ValueError
            unit_rate = known_value / known_quantity
            result = unit_rate * target_quantity
            return _SolvedValue(result, (unit_rate, result))
        if family == "weighted_average":
            values = [_fraction(value) for value in _sequence(params.get("values"))]
            weights = [_fraction(value) for value in _sequence(params.get("weights"))]
            if len(values) not in range(2, 9) or len(values) != len(weights) or any(weight <= 0 for weight in weights):
                raise ValueError
            weighted_total = sum(
                (value * weight for value, weight in zip(values, weights, strict=True)),
                Fraction(),
            )
            total_weight = sum(weights, Fraction())
            result = weighted_total / total_weight
            return _SolvedValue(result, (weighted_total, total_weight, result))
        if family == "partnership_share":
            capitals = [_fraction(value) for value in _sequence(params.get("capitals"))]
            durations = [_fraction(value) for value in _sequence(params.get("durations"))]
            total_profit = _fraction(params["total_profit"])
            requested_index = params.get("requested_index")
            if (
                len(capitals) not in range(2, 9)
                or len(capitals) != len(durations)
                or any(value <= 0 for value in capitals + durations)
                or total_profit < 0
                or isinstance(requested_index, bool)
                or not isinstance(requested_index, int)
                or requested_index not in range(len(capitals))
            ):
                raise ValueError
            shares = [capital * duration for capital, duration in zip(capitals, durations, strict=True)]
            total_share = sum(shares, Fraction())
            result = total_profit * shares[requested_index] / total_share
            return _SolvedValue(result, (total_share, result), "currency")
        if family == "percentage_change":
            original = _fraction(params["original"])
            updated = _fraction(params["updated"])
            if original <= 0 or updated < 0:
                raise ValueError
            difference = updated - original
            result = difference * 100 / original
            return _SolvedValue(result, (difference, result), "percent")
        if family == "simple_probability":
            favorable = _positive_int(params.get("favorable"), maximum=10**9)
            probability_total = _positive_int(params.get("total"), maximum=10**9)
            if favorable > probability_total:
                raise ValueError
            result = Fraction(favorable, probability_total)
            return _SolvedValue(result, (result,), "probability")
        if family == "rectangle_measure":
            length = _fraction(params["length"])
            width = _fraction(params["width"])
            requested = str(params.get("requested") or "")
            length_unit = _required_unit(params.get("length_unit"), {"centimetre", "metre", "kilometre"})
            if length <= 0 or width <= 0:
                raise ValueError
            if requested == "area":
                result = length * width
                return _SolvedValue(result, (result,), f"square_{length_unit}")
            if requested == "perimeter":
                side_sum = length + width
                result = 2 * side_sum
                return _SolvedValue(result, (side_sum, result), length_unit)
            raise ValueError
        if family == "discount_price":
            marked_price = _fraction(params["marked_price"])
            discount_percent = _fraction(params["discount_percent"])
            requested = str(params.get("requested") or "")
            if marked_price <= 0 or discount_percent < 0 or discount_percent > 100:
                raise ValueError
            discount_amount = marked_price * discount_percent / 100
            if requested == "discount_amount":
                return _SolvedValue(discount_amount, (discount_amount,), "currency")
            if requested == "sale_price":
                result = marked_price - discount_amount
                return _SolvedValue(result, (discount_amount, result), "currency")
            raise ValueError
        if family == "simultaneous_linear_equations":
            a1 = _fraction(params["a1"])
            b1 = _fraction(params["b1"])
            c1 = _fraction(params["c1"])
            a2 = _fraction(params["a2"])
            b2 = _fraction(params["b2"])
            c2 = _fraction(params["c2"])
            requested = str(params.get("requested") or "")
            determinant = a1 * b2 - a2 * b1
            if not determinant:
                raise ValueError
            if requested == "x":
                equation_numerator = c1 * b2 - c2 * b1
            elif requested == "y":
                equation_numerator = a1 * c2 - a2 * c1
            else:
                raise ValueError
            result = equation_numerator / determinant
            return _SolvedValue(result, (determinant, equation_numerator, result))
        if family == "triangle_measure":
            requested = str(params.get("requested") or "")
            length_unit = _required_unit(params.get("length_unit"), {"centimetre", "metre", "kilometre"})
            if requested == "area":
                base = _fraction(params["base"])
                height = _fraction(params["height"])
                if base <= 0 or height <= 0:
                    raise ValueError
                product = base * height
                result = product / 2
                return _SolvedValue(result, (product, result), f"square_{length_unit}")
            if requested == "perimeter":
                sides = [_fraction(value) for value in _sequence(params.get("sides"))]
                if (
                    len(sides) != 3
                    or any(side <= 0 for side in sides)
                    or any(sides[index] >= sum(sides, Fraction()) - sides[index] for index in range(3))
                ):
                    raise ValueError
                result = sum(sides, Fraction())
                return _SolvedValue(result, (result,), length_unit)
            raise ValueError
        if family == "permutation_combination":
            item_count = _bounded_int(params.get("n"), minimum=0, maximum=100)
            selection_count = _bounded_int(params.get("r"), minimum=0, maximum=item_count)
            requested = str(params.get("requested") or "")
            if requested == "permutation":
                result = perm(item_count, selection_count)
            elif requested == "combination":
                result = comb(item_count, selection_count)
            else:
                raise ValueError
            return _SolvedValue(result, (result,))
        if family == "inverse_proportion":
            known_quantity = _fraction(params["known_quantity"])
            known_value = _fraction(params["known_value"])
            target_quantity = _fraction(params["target_quantity"])
            if known_quantity <= 0 or known_value < 0 or target_quantity <= 0:
                raise ValueError
            constant_product = known_quantity * known_value
            result = constant_product / target_quantity
            return _SolvedValue(result, (constant_product, result))
        if family == "quadratic_equation_root":
            coefficient_a = _bounded_int(params.get("a"), minimum=-(10**6), maximum=10**6)
            coefficient_b = _bounded_int(params.get("b"), minimum=-(10**6), maximum=10**6)
            coefficient_c = _bounded_int(params.get("c"), minimum=-(10**6), maximum=10**6)
            requested = str(params.get("requested") or "")
            if not coefficient_a or requested not in {"smaller", "larger"}:
                raise ValueError
            discriminant = coefficient_b**2 - 4 * coefficient_a * coefficient_c
            if discriminant <= 0 or discriminant > 10**12:
                raise ValueError
            square_root = isqrt(discriminant)
            if square_root * square_root != discriminant:
                raise ValueError
            roots = sorted(
                (
                    Fraction(-coefficient_b - square_root, 2 * coefficient_a),
                    Fraction(-coefficient_b + square_root, 2 * coefficient_a),
                )
            )
            result = roots[0] if requested == "smaller" else roots[1]
            return _SolvedValue(result, (discriminant, square_root, result))
        if family == "age_ratio":
            older_ratio = _positive_int(params.get("older_ratio"), maximum=1000)
            younger_ratio = _positive_int(params.get("younger_ratio"), maximum=1000)
            age_difference = _fraction(params["age_difference"])
            years_offset = _fraction(params.get("years_offset", 0))
            requested = str(params.get("requested") or "")
            if older_ratio <= younger_ratio or age_difference <= 0 or age_difference > 200 or abs(years_offset) > 200:
                raise ValueError
            scale = age_difference / (older_ratio - younger_ratio)
            if requested == "older_present":
                referenced_age = older_ratio * scale
            elif requested == "younger_present":
                referenced_age = younger_ratio * scale
            else:
                raise ValueError
            result = referenced_age - years_offset
            if referenced_age <= 0 or referenced_age > 200 or result <= 0 or result > 200:
                raise ValueError
            return _SolvedValue(result, (scale, referenced_age, result), "year")
        if family == "boat_stream":
            boat_speed = _fraction(params["boat_speed"])
            stream_speed = _fraction(params["stream_speed"])
            requested = str(params.get("requested") or "")
            speed_unit = _required_unit(params.get("speed_unit"), {"kilometre/hour", "metre/second"})
            distance_unit = _required_unit(params.get("distance_unit"), {"kilometre", "metre"})
            compatible = {
                "kilometre/hour": ("kilometre", "hour"),
                "metre/second": ("metre", "second"),
            }
            expected_distance_unit, time_unit = compatible[speed_unit]
            if boat_speed <= stream_speed or stream_speed <= 0 or distance_unit != expected_distance_unit:
                raise ValueError
            if requested.startswith("upstream"):
                effective_speed = boat_speed - stream_speed
            elif requested.startswith("downstream"):
                effective_speed = boat_speed + stream_speed
            else:
                raise ValueError
            if requested.endswith("_speed"):
                return _SolvedValue(effective_speed, (effective_speed,), speed_unit)
            if requested.endswith("_time"):
                distance = _fraction(params["distance"])
                if distance <= 0:
                    raise ValueError
                result = distance / effective_speed
                return _SolvedValue(result, (effective_speed, result), time_unit)
            raise ValueError
        if family == "circle_measure":
            radius = _fraction(params["radius"])
            pi_numerator = _positive_int(params.get("pi_numerator"), maximum=10000)
            pi_denominator = _positive_int(params.get("pi_denominator"), maximum=10000)
            pi_value = Fraction(pi_numerator, pi_denominator)
            requested = str(params.get("requested") or "")
            length_unit = _required_unit(params.get("length_unit"), {"centimetre", "metre", "kilometre"})
            if radius <= 0 or not Fraction(3) < pi_value < Fraction(4):
                raise ValueError
            if requested == "area":
                result = pi_value * radius * radius
                return _SolvedValue(result, (result,), f"square_{length_unit}")
            if requested == "circumference":
                result = 2 * pi_value * radius
                return _SolvedValue(result, (result,), length_unit)
            raise ValueError
        if family == "mixture_replacement":
            total_volume = _fraction(params["total_volume"])
            removed_volume = _fraction(params["removed_volume"])
            initial_percent = _fraction(params["initial_concentration_percent"])
            replacement_percent = _fraction(params["replacement_concentration_percent"])
            repetitions = _positive_int(params.get("repetitions"), maximum=20)
            if (
                total_volume <= 0
                or removed_volume <= 0
                or removed_volume > total_volume
                or not 0 <= initial_percent <= 100
                or not 0 <= replacement_percent <= 100
            ):
                raise ValueError
            retention = (total_volume - removed_volume) / total_volume
            result = replacement_percent + (initial_percent - replacement_percent) * retention**repetitions
            return _SolvedValue(result, (retention, result), "percent")
        if family == "mean_median_mode":
            raw_values = _sequence(params.get("values"))
            requested = str(params.get("requested") or "")
            if len(raw_values) not in range(2, 21):
                raise ValueError
            values = [_fraction(value) for value in raw_values]
            if requested == "mean":
                total = sum(values, Fraction())
                result = total / len(values)
                return _SolvedValue(result, (total, result))
            if requested == "median":
                ordered = sorted(values)
                middle = len(ordered) // 2
                result = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
                return _SolvedValue(result, (result,))
            if requested == "mode":
                counts = {value: values.count(value) for value in set(values)}
                highest = max(counts.values())
                modes = [value for value, count in counts.items() if count == highest]
                if highest < 2 or len(modes) != 1:
                    raise ValueError
                return _SolvedValue(modes[0], (modes[0],))
            raise ValueError
        if family == "train_crossing":
            train_length = _fraction(params["train_length"])
            object_length = _fraction(params.get("object_length", 0))
            speed = _fraction(params["speed"])
            speed_unit = _required_unit(params.get("speed_unit"), {"kilometre/hour", "metre/second"})
            length_unit = _required_unit(params.get("length_unit"), {"metre"})
            if train_length <= 0 or object_length < 0 or speed <= 0 or length_unit != "metre":
                raise ValueError
            speed_metres_per_second = speed * Fraction(5, 18) if speed_unit == "kilometre/hour" else speed
            total_length = train_length + object_length
            result = total_length / speed_metres_per_second
            if result <= 0 or result > 86400:
                raise ValueError
            return _SolvedValue(
                result,
                (speed_metres_per_second, total_length, result),
                "second",
            )
        if family == "solid_measure":
            shape = str(params.get("shape") or "")
            requested = str(params.get("requested") or "")
            length_unit = _required_unit(params.get("length_unit"), {"centimetre", "metre"})
            if shape == "cuboid":
                length = _fraction(params["length"])
                width = _fraction(params["width"])
                height = _fraction(params["height"])
                if min(length, width, height) <= 0:
                    raise ValueError
                if requested == "volume":
                    result = length * width * height
                    return _SolvedValue(result, (result,), f"cubic_{length_unit}")
                if requested == "total_surface_area":
                    result = 2 * (length * width + width * height + height * length)
                    return _SolvedValue(result, (result,), f"square_{length_unit}")
                raise ValueError
            if shape == "cylinder":
                radius = _fraction(params["radius"])
                height = _fraction(params["height"])
                pi_value = Fraction(
                    _positive_int(params.get("pi_numerator"), maximum=10000),
                    _positive_int(params.get("pi_denominator"), maximum=10000),
                )
                if radius <= 0 or height <= 0 or not Fraction(3) < pi_value < Fraction(4):
                    raise ValueError
                if requested == "volume":
                    result = pi_value * radius * radius * height
                    return _SolvedValue(result, (result,), f"cubic_{length_unit}")
                if requested == "curved_surface_area":
                    result = 2 * pi_value * radius * height
                    return _SolvedValue(result, (result,), f"square_{length_unit}")
                if requested == "total_surface_area":
                    result = 2 * pi_value * radius * (radius + height)
                    return _SolvedValue(result, (result,), f"square_{length_unit}")
                raise ValueError
            raise ValueError
        if family == "successive_percentage_change":
            initial_value = _fraction(params["initial_value"])
            changes = [_fraction(value) for value in _sequence(params.get("changes_percent"))]
            requested = str(params.get("requested") or "")
            if (
                initial_value <= 0
                or len(changes) not in range(2, 11)
                or any(change < -100 or change > 1000 for change in changes)
            ):
                raise ValueError
            multiplier = Fraction(1)
            for change in changes:
                multiplier *= Fraction(1) + change / 100
            final_value = initial_value * multiplier
            if requested == "final_value":
                result = final_value
            elif requested == "net_change_percent":
                result = (multiplier - 1) * 100
            else:
                raise ValueError
            return _SolvedValue(result, (multiplier, result))
        if family == "work_wages":
            efficiencies = [_fraction(value) for value in _sequence(params.get("efficiencies"))]
            durations = [_fraction(value) for value in _sequence(params.get("durations"))]
            total_wages = _fraction(params["total_wages"])
            requested_index = params.get("requested_index")
            if (
                len(efficiencies) not in range(2, 9)
                or len(efficiencies) != len(durations)
                or any(value <= 0 for value in efficiencies + durations)
                or total_wages < 0
                or isinstance(requested_index, bool)
                or not isinstance(requested_index, int)
                or requested_index not in range(len(efficiencies))
            ):
                raise ValueError
            contributions = [
                efficiency * duration for efficiency, duration in zip(efficiencies, durations, strict=True)
            ]
            total_contribution = sum(contributions, Fraction())
            result = total_wages * contributions[requested_index] / total_contribution
            return _SolvedValue(result, (total_contribution, result), "currency")
        if family == "data_table_aggregate":
            values = [_fraction(value) for value in _sequence(params.get("values"))]
            requested = str(params.get("requested") or "")
            if len(values) not in range(2, 21):
                raise ValueError
            total = sum(values, Fraction())
            if requested == "sum":
                return _SolvedValue(total, (total,))
            if requested == "average":
                result = total / len(values)
                return _SolvedValue(result, (total, result))
            if requested == "range":
                result = max(values) - min(values)
                return _SolvedValue(result, (result,))
            if requested == "percentage_share":
                requested_index = params.get("requested_index")
                if (
                    total <= 0
                    or any(value < 0 for value in values)
                    or isinstance(requested_index, bool)
                    or not isinstance(requested_index, int)
                    or requested_index not in range(len(values))
                ):
                    raise ValueError
                result = values[requested_index] * 100 / total
                return _SolvedValue(result, (total, result), "percent")
            raise ValueError
        if family == "integer_division":
            dividend = _bounded_int(params.get("dividend"), minimum=0, maximum=10**15)
            divisor = _positive_int(params.get("divisor"), maximum=10**9)
            requested = str(params.get("requested") or "")
            quotient, integer_remainder = divmod(dividend, divisor)
            if requested == "quotient":
                result = quotient
            elif requested == "remainder":
                result = integer_remainder
            else:
                raise ValueError
            return _SolvedValue(result, (quotient, integer_remainder, result))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise DeterministicVerificationError(
            "math_proof_invalid", "The mathematics proof parameters are invalid."
        ) from exc
    raise DeterministicVerificationError(
        "math_family_unsupported", f"Unsupported mathematics family: {family or 'blank'}."
    )


def _solve_reasoning(family: str, raw: Any) -> _SolvedValue:
    params = _mapping(raw)
    result: Any
    try:
        if family == "arithmetic_series_next":
            values = [_fraction(value) for value in _sequence(params.get("sequence"))]
            if len(values) < 3:
                raise ValueError
            differences = [right - left for left, right in zip(values, values[1:], strict=False)]
            if len(set(differences)) != 1:
                raise ValueError
            result = values[-1] + differences[0]
            return _SolvedValue(result, (differences[0], result))
        if family == "ordering_rank":
            values = list(_sequence(params.get("values")))
            target = params.get("target")
            direction = str(params.get("direction") or "")
            if len(values) != len(set(map(str, values))) or target not in values:
                raise ValueError
            if direction == "ascending":
                ordered = sorted(values)
            elif direction == "descending":
                ordered = sorted(values, reverse=True)
            else:
                raise ValueError
            result = ordered.index(target) + 1
            return _SolvedValue(result, (result,))
        if family == "odd_one_out_tag":
            tags = [str(value) for value in _sequence(params.get("tags"))]
            if len(tags) != 4:
                raise ValueError
            counts = {tag: tags.count(tag) for tag in set(tags)}
            unique = [index for index, tag in enumerate(tags) if counts[tag] == 1]
            if len(unique) != 1 or sorted(counts.values()) != [1, 3]:
                raise ValueError
            return _SolvedValue(unique[0], (unique[0],))
        if family == "coding_shift":
            source = str(params.get("source") or "").upper()
            shift = params.get("shift")
            direction = str(params.get("direction") or "")
            if not source or not source.isascii() or not source.isalpha():
                raise ValueError
            if isinstance(shift, bool) or not isinstance(shift, int) or shift not in range(1, 26):
                raise ValueError
            signed_shift = shift if direction == "encode" else -shift if direction == "decode" else 0
            if not signed_shift:
                raise ValueError
            result = "".join(chr((ord(character) - ord("A") + signed_shift) % 26 + ord("A")) for character in source)
            return _SolvedValue(result, (result,))
        if family == "direction_path":
            moves = _sequence(params.get("moves"))
            if not moves or len(moves) > 20:
                raise ValueError
            x = Fraction()
            y = Fraction()
            vectors = {
                "N": (0, 1),
                "S": (0, -1),
                "E": (1, 0),
                "W": (-1, 0),
            }
            for move in moves:
                if not isinstance(move, Mapping):
                    raise ValueError
                direction = str(move.get("direction") or "")
                distance = _fraction(move.get("distance"))
                if direction not in vectors or distance <= 0:
                    raise ValueError
                dx, dy = vectors[direction]
                x += dx * distance
                y += dy * distance
            if not x and not y:
                raise ValueError
            horizontal = "E" if x > 0 else "W" if x < 0 else ""
            vertical = "N" if y > 0 else "S" if y < 0 else ""
            result = vertical + horizontal
            return _SolvedValue(result, (x, y, result))
        if family == "ordering_constraints":
            items = [str(value) for value in _sequence(params.get("items"))]
            constraints = _sequence(params.get("constraints"))
            target = str(params.get("target") or "")
            if len(items) not in range(2, 8) or len(set(items)) != len(items) or target not in items:
                raise ValueError
            valid_orders: list[tuple[str, ...]] = []
            for order in permutations(items):
                positions = {item: index for index, item in enumerate(order)}
                if all(_constraint_holds(rule, positions) for rule in constraints):
                    valid_orders.append(order)
            if not valid_orders:
                raise ValueError
            ranks = {order.index(target) + 1 for order in valid_orders}
            if len(ranks) != 1:
                raise ValueError
            result = ranks.pop()
            return _SolvedValue(result, (len(valid_orders), result))
        if family == "syllogism_finite_sets":
            raw_sets = _mapping(params.get("sets"))
            sets = {str(name): {str(value) for value in _sequence(members)} for name, members in raw_sets.items()}
            left = str(params.get("left") or "")
            right = str(params.get("right") or "")
            relation = str(params.get("relation") or "")
            if left not in sets or right not in sets or not sets[left]:
                raise ValueError
            if relation == "all":
                result = sets[left] <= sets[right]
            elif relation == "some":
                result = bool(sets[left] & sets[right])
            elif relation == "none":
                result = sets[left].isdisjoint(sets[right])
            else:
                raise ValueError
            return _SolvedValue(result, (result,))
        if family == "analogy_mapping":
            mapping = _mapping(params.get("mapping"))
            query = str(params.get("query") or "")
            if not mapping or query not in mapping:
                raise ValueError
            result = str(mapping[query])
            if not result:
                raise ValueError
            return _SolvedValue(result, (result,))
        if family == "calendar_weekday_offset":
            start_weekday = _bounded_int(params.get("start_weekday"), minimum=0, maximum=6)
            day_offset = _bounded_int(params.get("day_offset"), minimum=0, maximum=366000)
            result = (start_weekday + day_offset) % 7
            return _SolvedValue(result, (result,))
        if family == "clock_smaller_angle":
            hour = _bounded_int(params.get("hour"), minimum=0, maximum=23) % 12
            minute = _bounded_int(params.get("minute"), minimum=0, maximum=59)
            raw_angle = abs(Fraction(60 * hour - 11 * minute, 2))
            result = min(raw_angle, Fraction(360) - raw_angle)
            return _SolvedValue(result, (raw_angle, result), "degree")
        if family == "geometric_series_next":
            values = [_fraction(value) for value in _sequence(params.get("sequence"))]
            if len(values) not in range(3, 9) or any(not value for value in values):
                raise ValueError
            ratio = values[1] / values[0]
            if (
                not ratio
                or abs(ratio) > 100
                or any(right != left * ratio for left, right in zip(values, values[1:], strict=False))
            ):
                raise ValueError
            result = values[-1] * ratio
            return _SolvedValue(result, (ratio, result))
        if family == "alphabet_series_next":
            alphabet_positions = [
                _bounded_int(value, minimum=1, maximum=26) for value in _sequence(params.get("positions"))
            ]
            if len(alphabet_positions) not in range(3, 13):
                raise ValueError
            alphabet_steps = [
                (right - left) % 26 for left, right in zip(alphabet_positions, alphabet_positions[1:], strict=False)
            ]
            if not alphabet_steps[0] or len(set(alphabet_steps)) != 1:
                raise ValueError
            result = ((alphabet_positions[-1] - 1 + alphabet_steps[0]) % 26) + 1
            return _SolvedValue(result, (alphabet_steps[0], result))
        if family == "quadratic_series_next":
            values = [_fraction(value) for value in _sequence(params.get("sequence"))]
            if len(values) not in range(4, 10):
                raise ValueError
            differences = [right - left for left, right in zip(values, values[1:], strict=False)]
            second_differences = [right - left for left, right in zip(differences, differences[1:], strict=False)]
            if len(set(second_differences)) != 1 or not second_differences[0]:
                raise ValueError
            next_difference = differences[-1] + second_differences[0]
            result = values[-1] + next_difference
            return _SolvedValue(result, (second_differences[0], next_difference, result))
        if family == "alternating_arithmetic_series_next":
            values = [_fraction(value) for value in _sequence(params.get("sequence"))]
            if len(values) not in range(6, 13):
                raise ValueError
            subsequences = (values[::2], values[1::2])
            steps: list[Fraction] = []
            for subsequence in subsequences:
                differences = [right - left for left, right in zip(subsequence, subsequence[1:], strict=False)]
                if len(differences) < 2 or len(set(differences)) != 1:
                    raise ValueError
                steps.append(differences[0])
            if not any(steps):
                raise ValueError
            next_parity = len(values) % 2
            result = subsequences[next_parity][-1] + steps[next_parity]
            return _SolvedValue(result, (steps[0], steps[1], result))
        if family == "two_set_cardinality":
            first_count = _bounded_int(params.get("first_count"), minimum=0, maximum=10**9)
            second_count = _bounded_int(params.get("second_count"), minimum=0, maximum=10**9)
            intersection = _bounded_int(params.get("intersection"), minimum=0, maximum=10**9)
            requested = str(params.get("requested") or "")
            if intersection > min(first_count, second_count):
                raise ValueError
            union = first_count + second_count - intersection
            if requested == "union":
                return _SolvedValue(union, (union,))
            if requested == "only_first":
                result = first_count - intersection
            elif requested == "only_second":
                result = second_count - intersection
            elif requested == "neither":
                total_population = _bounded_int(params.get("total_population"), minimum=0, maximum=10**9)
                if total_population < union:
                    raise ValueError
                result = total_population - union
            else:
                raise ValueError
            return _SolvedValue(result, (union, result))
        if family == "bidirectional_rank_total":
            rank_from_left = _positive_int(params.get("rank_from_left"), maximum=10**9)
            rank_from_right = _positive_int(params.get("rank_from_right"), maximum=10**9)
            result = rank_from_left + rank_from_right - 1
            return _SolvedValue(result, (result,))
        if family == "clock_mirror_time":
            hour = _bounded_int(params.get("hour"), minimum=1, maximum=12)
            minute = _bounded_int(params.get("minute"), minimum=0, maximum=59)
            shown_minutes = (hour % 12) * 60 + minute
            mirror_minutes = (720 - shown_minutes) % 720
            mirror_hour = mirror_minutes // 60 or 12
            mirror_minute = mirror_minutes % 60
            result = f"{mirror_hour:02d}:{mirror_minute:02d}"
            return _SolvedValue(result, (result,))
        if family == "three_set_cardinality":
            first = _bounded_int(params.get("first_count"), minimum=0, maximum=10**9)
            second = _bounded_int(params.get("second_count"), minimum=0, maximum=10**9)
            third = _bounded_int(params.get("third_count"), minimum=0, maximum=10**9)
            first_second = _bounded_int(params.get("first_second_intersection"), minimum=0, maximum=10**9)
            first_third = _bounded_int(params.get("first_third_intersection"), minimum=0, maximum=10**9)
            second_third = _bounded_int(params.get("second_third_intersection"), minimum=0, maximum=10**9)
            all_three = _bounded_int(params.get("all_three_intersection"), minimum=0, maximum=10**9)
            if (
                first_second > min(first, second)
                or first_third > min(first, third)
                or second_third > min(second, third)
                or all_three > min(first_second, first_third, second_third)
            ):
                raise ValueError
            only_first = first - first_second - first_third + all_three
            only_second = second - first_second - second_third + all_three
            only_third = third - first_third - second_third + all_three
            if min(only_first, only_second, only_third) < 0:
                raise ValueError
            union = first + second + third - first_second - first_third - second_third + all_three
            requested = str(params.get("requested") or "")
            if requested == "union":
                return _SolvedValue(union, (union,))
            if requested == "exactly_one":
                result = only_first + only_second + only_third
            elif requested == "neither":
                total_population = _bounded_int(params.get("total_population"), minimum=0, maximum=10**9)
                if total_population < union:
                    raise ValueError
                result = total_population - union
            else:
                raise ValueError
            return _SolvedValue(result, (union, result))
        if family == "family_tree_relation":
            result = _solve_family_tree_relation(params)
            return _SolvedValue(result, (result,))
        if family == "circular_seating_constraints":
            result, valid_count = _solve_circular_seating(params)
            return _SolvedValue(result, (valid_count, result))
        if family == "calendar_date_weekday":
            year = _bounded_int(params.get("year"), minimum=1900, maximum=2100)
            month = _bounded_int(params.get("month"), minimum=1, maximum=12)
            day = _bounded_int(params.get("day"), minimum=1, maximum=31)
            result = datetime(year, month, day).weekday()
            return _SolvedValue(result, (result,))
        if family == "direction_turn_path":
            result, trace = _solve_direction_turn_path(params)
            return _SolvedValue(result, trace)
        if family == "logical_truth_assignment":
            result, valid_count = _solve_logical_truth_assignment(params)
            return _SolvedValue(result, (valid_count, result))
    except (TypeError, ValueError) as exc:
        raise DeterministicVerificationError(
            "reasoning_proof_invalid", "The reasoning puzzle is inconsistent or under-constrained."
        ) from exc
    raise DeterministicVerificationError(
        "reasoning_family_unsupported", f"Unsupported reasoning family: {family or 'blank'}."
    )


def _constraint_holds(rule: Any, positions: Mapping[str, int]) -> bool:
    if not isinstance(rule, Mapping):
        raise ValueError
    before = str(rule.get("before") or "")
    after = str(rule.get("after") or "")
    if before not in positions or after not in positions or before == after:
        raise ValueError
    return positions[before] < positions[after]


def _solve_direction_turn_path(params: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    headings = ("N", "E", "S", "W")
    start_direction = str(params.get("start_direction") or "")
    commands = _sequence(params.get("commands"))
    requested = str(params.get("requested") or "")
    if start_direction not in headings or len(commands) not in range(1, 21):
        raise ValueError
    heading_index = headings.index(start_direction)
    x = Fraction()
    y = Fraction()
    turn_offsets = {"straight": 0, "right": 1, "around": 2, "left": -1}
    vectors = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
    for raw_command in commands:
        if not isinstance(raw_command, Mapping):
            raise ValueError
        turn = str(raw_command.get("turn") or "")
        distance = _fraction(raw_command.get("distance"))
        if turn not in turn_offsets or distance <= 0:
            raise ValueError
        heading_index = (heading_index + turn_offsets[turn]) % len(headings)
        dx, dy = vectors[headings[heading_index]]
        x += dx * distance
        y += dy * distance
    if requested == "final_direction":
        result = headings[heading_index]
        return result, (result,)
    if requested == "net_direction":
        if not x and not y:
            raise ValueError
        horizontal = "E" if x > 0 else "W" if x < 0 else ""
        vertical = "N" if y > 0 else "S" if y < 0 else ""
        result = vertical + horizontal
        return result, (x, y, result)
    raise ValueError


def _solve_logical_truth_assignment(params: Mapping[str, Any]) -> tuple[bool, int]:
    raw_items = _sequence(params.get("items"))
    items = [str(value) for value in raw_items]
    constraints = _sequence(params.get("constraints"))
    target = str(params.get("target") or "")
    if (
        len(items) not in range(2, 9)
        or len(set(items)) != len(items)
        or any(not item or len(item) > 40 for item in items)
        or target not in items
        or len(constraints) not in range(1, 21)
    ):
        raise ValueError
    answers: set[bool] = set()
    valid_count = 0
    for values in product((False, True), repeat=len(items)):
        assignment = dict(zip(items, values, strict=True))
        if not all(_logical_constraint_holds(rule, assignment) for rule in constraints):
            continue
        valid_count += 1
        answers.add(assignment[target])
    if not valid_count or len(answers) != 1:
        raise ValueError
    return answers.pop(), valid_count


def _logical_constraint_holds(rule: Any, assignment: Mapping[str, bool]) -> bool:
    if not isinstance(rule, Mapping):
        raise ValueError
    kind = str(rule.get("type") or "")
    if kind == "is":
        item = str(rule.get("item") or "")
        value = rule.get("value")
        if item not in assignment or not isinstance(value, bool):
            raise ValueError
        return assignment[item] is value
    if kind in {"equal", "not_equal", "implies"}:
        left = str(rule.get("left") or "")
        right = str(rule.get("right") or "")
        if left not in assignment or right not in assignment or left == right:
            raise ValueError
        if kind == "equal":
            return assignment[left] is assignment[right]
        if kind == "not_equal":
            return assignment[left] is not assignment[right]
        return not assignment[left] or assignment[right]
    if kind in {"exactly_one", "at_least_one"}:
        members = [str(value) for value in _sequence(rule.get("items"))]
        if (
            len(members) not in range(2, len(assignment) + 1)
            or len(set(members)) != len(members)
            or any(member not in assignment for member in members)
        ):
            raise ValueError
        true_count = sum(assignment[member] for member in members)
        return true_count == 1 if kind == "exactly_one" else true_count >= 1
    raise ValueError


def _solve_family_tree_relation(params: Mapping[str, Any]) -> str:
    raw_people = _mapping(params.get("people"))
    if len(raw_people) not in range(2, 16):
        raise ValueError
    people = {str(name): str(gender) for name, gender in raw_people.items()}
    if any(not name or len(name) > 40 or gender not in {"male", "female"} for name, gender in people.items()):
        raise ValueError
    parent_edges = _sequence(params.get("parent_edges"))
    if not parent_edges or len(parent_edges) > 30:
        raise ValueError
    parents: dict[str, set[str]] = {name: set() for name in people}
    children: dict[str, set[str]] = {name: set() for name in people}
    for raw_edge in parent_edges:
        if not isinstance(raw_edge, Mapping):
            raise ValueError
        parent = str(raw_edge.get("parent") or "")
        child = str(raw_edge.get("child") or "")
        if parent not in people or child not in people or parent == child:
            raise ValueError
        parents[child].add(parent)
        children[parent].add(child)
        if len(parents[child]) > 2:
            raise ValueError

    def descendants(name: str, visiting: set[str]) -> set[str]:
        if name in visiting:
            raise ValueError
        next_visiting = {*visiting, name}
        result: set[str] = set()
        for child in children[name]:
            result.add(child)
            result.update(descendants(child, next_visiting))
        return result

    for person in people:
        descendants(person, set())

    subject = str(params.get("subject") or "")
    reference = str(params.get("reference") or "")
    if subject not in people or reference not in people or subject == reference:
        raise ValueError
    gender = people[subject]
    relations: set[str] = set()
    if subject in parents[reference]:
        relations.add("father" if gender == "male" else "mother")
    if subject in children[reference]:
        relations.add("son" if gender == "male" else "daughter")
    if parents[subject] & parents[reference]:
        relations.add("brother" if gender == "male" else "sister")
    reference_grandparents = {grandparent for parent in parents[reference] for grandparent in parents[parent]}
    if subject in reference_grandparents:
        relations.add("grandfather" if gender == "male" else "grandmother")
    subject_grandparents = {grandparent for parent in parents[subject] for grandparent in parents[parent]}
    if reference in subject_grandparents:
        relations.add("grandson" if gender == "male" else "granddaughter")
    if any(parents[subject] & parents[parent] for parent in parents[reference]):
        relations.add("uncle" if gender == "male" else "aunt")
    if any(parents[parent] & parents[reference] for parent in parents[subject]):
        relations.add("nephew" if gender == "male" else "niece")
    if len(relations) != 1:
        raise ValueError
    return relations.pop()


def _solve_circular_seating(params: Mapping[str, Any]) -> tuple[str, int]:
    raw_items = _sequence(params.get("items"))
    if len(raw_items) not in range(4, 9):
        raise ValueError
    items = [str(value) for value in raw_items]
    anchor = str(params.get("anchor") or "")
    direction = str(params.get("direction") or "")
    query_steps = params.get("query_steps")
    constraints = _sequence(params.get("constraints"))
    if (
        len(set(items)) != len(items)
        or any(not item or len(item) > 40 for item in items)
        or anchor not in items
        or direction not in {"clockwise", "counterclockwise"}
        or isinstance(query_steps, bool)
        or not isinstance(query_steps, int)
        or query_steps not in range(1, len(items))
        or len(constraints) not in range(1, 21)
    ):
        raise ValueError
    others = [item for item in items if item != anchor]
    answers: set[str] = set()
    valid_count = 0
    for tail in permutations(others):
        order = (anchor, *tail)
        positions = {item: index for index, item in enumerate(order)}
        if not all(_circular_constraint_holds(rule, positions, len(items)) for rule in constraints):
            continue
        valid_count += 1
        offset = query_steps if direction == "clockwise" else -query_steps
        answers.add(order[offset % len(items)])
    if not valid_count or len(answers) != 1:
        raise ValueError
    return answers.pop(), valid_count


def _circular_constraint_holds(
    rule: Any,
    positions: Mapping[str, int],
    item_count: int,
) -> bool:
    if not isinstance(rule, Mapping):
        raise ValueError
    kind = str(rule.get("type") or "")
    first = str(rule.get("first") or "")
    second = str(rule.get("second") or "")
    if first not in positions or second not in positions or first == second:
        raise ValueError
    clockwise_distance = (positions[second] - positions[first]) % item_count
    if kind == "adjacent":
        return clockwise_distance in {1, item_count - 1}
    if kind == "clockwise_adjacent":
        return clockwise_distance == 1
    if kind == "opposite":
        return item_count % 2 == 0 and clockwise_distance == item_count // 2
    if kind == "clockwise_steps":
        steps = rule.get("steps")
        if isinstance(steps, bool) or not isinstance(steps, int) or steps not in range(1, item_count):
            raise ValueError
        return clockwise_distance == steps
    raise ValueError


def _verify_explanation_values(proof: Mapping[str, Any], expected: Sequence[Any]) -> None:
    claimed = proof.get("explanation_values")
    if not isinstance(claimed, Sequence) or isinstance(claimed, (str, bytes)):
        raise DeterministicVerificationError(
            "explanation_steps_missing",
            "The proof must include machine-readable explanation values.",
        )
    if len(claimed) != len(expected) or any(
        not _values_equal(left, right) for left, right in zip(claimed, expected, strict=True)
    ):
        raise DeterministicVerificationError(
            "explanation_steps_invalid",
            "The explanation steps disagree with the deterministic solution trace.",
        )


def _verify_option_units(proof: Mapping[str, Any], expected: str) -> None:
    option_units = proof.get("option_units")
    if not isinstance(option_units, Sequence) or isinstance(option_units, (str, bytes)) or len(option_units) != 4:
        raise DeterministicVerificationError("units_missing", "The proof must provide a unit for every option.")
    normalized = [normalize_text(str(value)) for value in option_units]
    if any(value != normalize_text(expected) for value in normalized):
        raise DeterministicVerificationError("units_inconsistent", "Every option must use the proved answer unit.")


def _required_unit(value: Any, allowed: set[str]) -> str:
    unit = normalize_text(str(value or ""))
    if unit not in allowed:
        raise ValueError
    return unit


def _solve_evidence(candidate: Mapping[str, Any], proof: Mapping[str, Any]) -> str:
    answer = str(candidate.get("knowledge_answer_value") or "").strip()
    evidence = normalize_text(
        " ".join(str(candidate.get(name) or "") for name in ("canonical_claim", "evidence_summary"))
    )
    if not answer or normalize_text(answer) not in evidence:
        raise DeterministicVerificationError(
            "answer_not_in_evidence", "The atomic evidence does not contain the canonical answer."
        )
    evidence_values = proof.get("evidence_values")
    if not isinstance(evidence_values, Sequence) or isinstance(evidence_values, (str, bytes)):
        raise DeterministicVerificationError("proof_invalid", "Evidence proof values must be a list.")
    supported = [value for value in evidence_values if normalize_text(str(value)) in evidence]
    if len({normalize_text(str(value)) for value in supported}) != 1:
        raise DeterministicVerificationError(
            "answer_not_unique", "Atomic evidence supports zero or multiple displayed answers."
        )
    return answer


def _solve_evidence_span(candidate: Mapping[str, Any], proof: Mapping[str, Any]) -> str:
    """Prove one answer against a verbatim atomic span of the verified source."""
    answer = str(candidate.get("knowledge_answer_value") or "").strip()
    source = str(candidate.get("evidence_summary") or "")
    span = str(proof.get("evidence_span") or "").strip()
    if not span or span not in source:
        raise DeterministicVerificationError(
            "evidence_span_invalid",
            "The atomic evidence span is not an exact contiguous span of the verified source.",
        )
    if not answer or answer not in span:
        raise DeterministicVerificationError(
            "answer_not_in_evidence",
            "The atomic evidence span does not contain the canonical answer verbatim.",
        )
    evidence_values = proof.get("evidence_values")
    if not isinstance(evidence_values, Sequence) or isinstance(evidence_values, (str, bytes)):
        raise DeterministicVerificationError("proof_invalid", "Evidence proof values must be a list.")
    supported = {
        normalize_text(str(value)) for value in evidence_values if str(value).strip() and str(value).strip() in span
    }
    if supported != {normalize_text(answer)}:
        raise DeterministicVerificationError(
            "answer_not_unique", "The atomic evidence span supports zero or multiple displayed answers."
        )
    return answer


def _values_equal(value: Any, expected: Any) -> bool:
    try:
        return _fraction(value) == _fraction(expected)
    except (TypeError, ValueError, ZeroDivisionError):
        return normalize_text(str(value)) == normalize_text(str(expected))


def _fraction(value: Any) -> Fraction:
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, Fraction):
        result = value
        if result.numerator.bit_length() > 256 or result.denominator.bit_length() > 256:
            raise ValueError
        return result
    if isinstance(value, int):
        if abs(value) > 10**15:
            raise ValueError
        return Fraction(value)
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        text = str(value).strip().replace(",", "")
        if not text or len(text) > 64:
            raise ValueError
        try:
            decimal_value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError from exc
    if not decimal_value.is_finite() or (decimal_value and not -18 <= decimal_value.adjusted() <= 15):
        raise ValueError
    try:
        result = Fraction(decimal_value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError from exc
    if result.numerator.bit_length() > 256 or result.denominator.bit_length() > 256:
        raise ValueError
    return result


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError
    text = str(value).strip().replace(",", "")
    if not text or len(text) > 64:
        raise ValueError
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError from exc
    if not result.is_finite() or (result and not -18 <= result.adjusted() <= 15):
        raise ValueError
    return result


def _positive_int(value: Any, *, maximum: int = 10**9) -> int:
    if isinstance(value, bool):
        raise ValueError
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError from exc
    if str(result) != str(value).strip() or result <= 0 or result > maximum:
        raise ValueError
    return result


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    if value < minimum or value > maximum:
        raise ValueError
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeterministicVerificationError("proof_invalid", "Proof parameters must be an object.")
    return value


def _sequence(value: Any) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError
    return value


def _parse_datetime(value: Any, label: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise DeterministicVerificationError("source_date_invalid", f"The {label} timestamp is invalid.") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
