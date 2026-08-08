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
from decimal import Decimal, InvalidOperation
from fractions import Fraction
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "family": self.family,
            "expected_answer": self.expected_answer,
            "checks": dict(self.checks),
        }


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
        raise DeterministicVerificationError(
            "options_invalid", "Deterministic verification requires four options."
        )
    if isinstance(correct_index, bool) or not isinstance(correct_index, int) or correct_index not in range(4):
        raise DeterministicVerificationError(
            "answer_invalid", "Deterministic verification requires one declared answer."
        )

    _verify_option_quality(options, correct_index)
    _verify_language(candidate, subject)
    _verify_source_dates(candidate, now=now)

    proof = candidate.get("deterministic_proof")
    if proof is None:
        if require_subject_proof and subject in {"mathematics", "reasoning"}:
            raise DeterministicVerificationError(
                "proof_missing",
                f"{subject} candidates require a machine-checkable proof payload.",
            )
        return DeterministicResult(
            version=PROOF_VERSION,
            family="common",
            expected_answer=None,
            checks={
                "options_materially_distinct": True,
                "option_pattern_safe": True,
                "language_valid": True,
                "source_dates_valid": True,
                "unique_answer_proved": subject not in {"mathematics", "reasoning"},
            },
        )
    if not isinstance(proof, Mapping) or proof.get("version") != PROOF_VERSION:
        raise DeterministicVerificationError(
            "proof_invalid", "The deterministic proof version is missing or unsupported."
        )

    family = str(proof.get("family") or "").strip()
    expected: Any
    if subject == "mathematics":
        expected = _solve_mathematics(family, proof.get("parameters"))
    elif subject == "reasoning":
        expected = _solve_reasoning(family, proof.get("parameters"))
    elif family == "evidence_single_answer":
        expected = _solve_evidence(candidate, proof)
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
    matches = [index for index, value in enumerate(option_values) if _values_equal(value, expected)]
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
            "option_pattern_safe": True,
            "language_valid": True,
            "source_dates_valid": True,
            "solver_supported": True,
            "unique_answer_proved": True,
            "declared_answer_matches": True,
            "explanation_matches": True,
        },
    )


def _verify_option_quality(options: Sequence[Any], correct_index: int) -> None:
    material = [_material_option(value) for value in options]
    if any(not value for value in material) or len(set(material)) != 4:
        raise DeterministicVerificationError(
            "options_materially_duplicate",
            "Options are not materially distinct after labels and punctuation are removed.",
        )
    kinds = [_option_kind(value) for value in options]
    correct_kind = kinds[correct_index]
    if kinds.count(correct_kind) == 1 and len(set(kinds)) > 1:
        raise DeterministicVerificationError(
            "option_pattern_leakage",
            "The correct option is the only option with its visible value pattern.",
        )


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
    explanation = " ".join(
        str(candidate.get(name) or "")
        for name in ("explanation", "detailed_explanation")
    )
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
            raise DeterministicVerificationError(
                "terminology_invalid", "Terminology glossary must be an object."
            )
        for canonical, observed in terminology.items():
            if normalize_text(str(canonical)) != normalize_text(str(observed)):
                raise DeterministicVerificationError(
                    "translation_mismatch",
                    "Candidate terminology disagrees with the reviewed glossary.",
                )


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
        raise DeterministicVerificationError(
            "fact_not_effective", "The fact is not effective at verification time."
        )
    if expires and expires < current:
        raise DeterministicVerificationError(
            "source_stale", "The source fact expired before verification."
        )


def _solve_mathematics(family: str, raw: Any) -> Fraction:
    params = _mapping(raw)
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
            return result
        if family == "percentage_of":
            return _fraction(params["base"]) * _fraction(params["percent"]) / 100
        if family == "average":
            values = [_fraction(value) for value in _sequence(params.get("values"))]
            if not values:
                raise ValueError
            return sum(values, Fraction()) / len(values)
        if family == "ratio_share":
            left = _fraction(params["left_ratio"])
            right = _fraction(params["right_ratio"])
            total = _fraction(params["total"])
            requested = str(params.get("requested") or "")
            if left <= 0 or right <= 0 or requested not in {"left", "right"}:
                raise ValueError
            return total * (left if requested == "left" else right) / (left + right)
        if family == "simple_interest":
            return (
                _fraction(params["principal"])
                * _fraction(params["rate_percent"])
                * _fraction(params["years"])
                / 100
            )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise DeterministicVerificationError(
            "math_proof_invalid", "The mathematics proof parameters are invalid."
        ) from exc
    raise DeterministicVerificationError(
        "math_family_unsupported", f"Unsupported mathematics family: {family or 'blank'}."
    )


def _solve_reasoning(family: str, raw: Any) -> Any:
    params = _mapping(raw)
    try:
        if family == "arithmetic_series_next":
            values = [_fraction(value) for value in _sequence(params.get("sequence"))]
            if len(values) < 3:
                raise ValueError
            differences = [
                right - left for left, right in zip(values, values[1:], strict=False)
            ]
            if len(set(differences)) != 1:
                raise ValueError
            return values[-1] + differences[0]
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
            return ordered.index(target) + 1
        if family == "odd_one_out_tag":
            tags = [str(value) for value in _sequence(params.get("tags"))]
            if len(tags) != 4:
                raise ValueError
            counts = {tag: tags.count(tag) for tag in set(tags)}
            unique = [index for index, tag in enumerate(tags) if counts[tag] == 1]
            if len(unique) != 1 or sorted(counts.values()) != [1, 3]:
                raise ValueError
            return unique[0]
    except (TypeError, ValueError) as exc:
        raise DeterministicVerificationError(
            "reasoning_proof_invalid", "The reasoning puzzle is inconsistent or under-constrained."
        ) from exc
    raise DeterministicVerificationError(
        "reasoning_family_unsupported", f"Unsupported reasoning family: {family or 'blank'}."
    )


def _solve_evidence(candidate: Mapping[str, Any], proof: Mapping[str, Any]) -> str:
    answer = str(candidate.get("knowledge_answer_value") or "").strip()
    evidence = normalize_text(
        " ".join(
            str(candidate.get(name) or "")
            for name in ("canonical_claim", "evidence_summary")
        )
    )
    if not answer or normalize_text(answer) not in evidence:
        raise DeterministicVerificationError(
            "answer_not_in_evidence", "The atomic evidence does not contain the canonical answer."
        )
    evidence_values = proof.get("evidence_values")
    if not isinstance(evidence_values, Sequence) or isinstance(evidence_values, (str, bytes)):
        raise DeterministicVerificationError(
            "proof_invalid", "Evidence proof values must be a list."
        )
    supported = [value for value in evidence_values if normalize_text(str(value)) in evidence]
    if len({normalize_text(str(value)) for value in supported}) != 1:
        raise DeterministicVerificationError(
            "answer_not_unique", "Atomic evidence supports zero or multiple displayed answers."
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
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError
    try:
        return Fraction(Decimal(text))
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        raise ValueError from exc


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeterministicVerificationError(
            "proof_invalid", "Proof parameters must be an object."
        )
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
        raise DeterministicVerificationError(
            "source_date_invalid", f"The {label} timestamp is invalid."
        ) from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
