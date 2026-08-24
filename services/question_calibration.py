"""Answer-free classical item diagnostics for editorial review.

The report is deliberately advisory.  It never changes question status,
difficulty, or learner mastery, and it abstains until the configured evidence
gates are met.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    min_responses: int = 100
    min_unique_learners: int = 50
    min_group_size: int = 10
    low_facility: float = 0.20
    high_facility: float = 0.90
    low_discrimination: float = 0.10
    nonfunctioning_distractor_share: float = 0.05


def calibration_report(
    observations: Iterable[dict[str, Any]],
    *,
    policy: CalibrationPolicy | None = None,
) -> dict[str, Any]:
    """Aggregate first-response evidence without returning learner answers."""
    rules = policy or CalibrationPolicy()
    input_rows = 0
    usable: list[dict[str, Any]] = []
    for row in observations:
        input_rows += 1
        normalized = _normalize(row)
        if normalized is not None:
            usable.append(normalized)

    # Repeated exposure can otherwise make a small group of heavy users look
    # like an adequately sampled population. Keep only the learner's earliest
    # response to each question.
    usable.sort(key=lambda row: (row["completed_at"], row["attempt_id"]))
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in usable:
        unique.setdefault((row["question_id"], row["user_id"]), row)

    by_question: dict[str, list[dict[str, Any]]] = {}
    for row in unique.values():
        by_question.setdefault(row["question_id"], []).append(row)

    questions = [
        _question_diagnostic(question_id, rows, rules)
        for question_id, rows in sorted(by_question.items())
    ]
    calibratable = sum(item["recommendation"] != "collect_more_data" for item in questions)
    return {
        "policy": asdict(rules),
        "coverage": {
            "input_rows": input_rows,
            "usable_first_responses": len(unique),
            "discarded_rows": input_rows - len(unique),
            "questions_seen": len(questions),
            "questions_with_sufficient_evidence": calibratable,
            "questions_collecting_data": len(questions) - calibratable,
        },
        "questions": questions,
        "safety": {
            "aggregate_only": True,
            "automatic_retirement": False,
            "automatic_difficulty_change": False,
            "automatic_mastery_change": False,
        },
    }


def _question_diagnostic(
    question_id: str,
    rows: list[dict[str, Any]],
    policy: CalibrationPolicy,
) -> dict[str, Any]:
    sample_size = len(rows)
    correct_count = sum(1 for row in rows if row["is_correct"])
    facility = correct_count / sample_size
    lower, upper = _wilson_interval(correct_count, sample_size)
    discrimination, correct_group, incorrect_group = _point_biserial(rows)
    answered = [row for row in rows if row["selected_option"] is not None]
    distractor_shares = _distractor_shares(answered)

    reasons: list[str] = []
    sufficient = sample_size >= policy.min_responses and sample_size >= policy.min_unique_learners
    if not sufficient:
        recommendation = "collect_more_data"
        reasons.append("minimum_sample_not_met")
    else:
        if facility < policy.low_facility:
            reasons.append("facility_too_low")
        elif facility > policy.high_facility:
            reasons.append("facility_too_high")
        if min(correct_group, incorrect_group) < policy.min_group_size:
            reasons.append("discrimination_sample_not_met")
        elif discrimination is None:
            reasons.append("discrimination_not_estimable")
        elif discrimination < policy.low_discrimination:
            reasons.append("negative_discrimination" if discrimination < 0 else "low_discrimination")
        if any(share < policy.nonfunctioning_distractor_share for share in distractor_shares):
            reasons.append("nonfunctioning_distractor")
        if _difficulty_mismatch(str(rows[0]["authored_difficulty"]), facility):
            reasons.append("authored_difficulty_mismatch")
        recommendation = "editorial_review" if reasons else "retain"

    return {
        "question_id": question_id,
        "subject": rows[0]["subject"],
        "authored_difficulty": rows[0]["authored_difficulty"],
        "sample_size": sample_size,
        "unique_learners": sample_size,
        "facility": {
            "estimate": round(facility, 4),
            "wilson_95_lower": round(lower, 4),
            "wilson_95_upper": round(upper, 4),
        },
        "discrimination": {
            "point_biserial_rest_score": None if discrimination is None else round(discrimination, 4),
            "correct_group_size": correct_group,
            "incorrect_group_size": incorrect_group,
            "minimum_group_size_met": min(correct_group, incorrect_group) >= policy.min_group_size,
        },
        "distractors": {
            "answered_responses": len(answered),
            # Shares are sorted and intentionally detached from option indexes,
            # so an operator report cannot be used as an answer key.
            "selection_share_percent": [round(share * 100, 2) for share in sorted(distractor_shares)],
            "nonfunctioning_count": sum(
                share < policy.nonfunctioning_distractor_share for share in distractor_shares
            ),
        },
        "recommendation": recommendation,
        "reason_codes": reasons,
    }


def _normalize(row: dict[str, Any]) -> dict[str, Any] | None:
    question_id = str(row.get("question_id") or "").strip()
    attempt_id = str(row.get("attempt_id") or "").strip()
    user_id = str(row.get("user_id") or "").strip()
    completed_at = str(row.get("completed_at") or "").strip()
    is_correct = row.get("is_correct")
    score = row.get("score")
    total = row.get("total")
    if not question_id or not attempt_id or not user_id or not completed_at or not isinstance(is_correct, bool):
        return None
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 1:
        return None
    selected = row.get("selected_option")
    correct = row.get("correct_option")
    if selected is not None and (isinstance(selected, bool) or not isinstance(selected, int) or selected not in range(4)):
        return None
    if isinstance(correct, bool) or not isinstance(correct, int) or correct not in range(4):
        return None
    try:
        datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return {
        "question_id": question_id,
        "attempt_id": attempt_id,
        "user_id": user_id,
        "completed_at": completed_at,
        "is_correct": is_correct,
        "selected_option": selected,
        "correct_option": correct,
        "score": float(score),
        "total": float(total),
        "subject": str(row.get("subject") or "unknown").strip() or "unknown",
        "authored_difficulty": str(row.get("authored_difficulty") or "unknown").strip().lower() or "unknown",
    }


def _wilson_interval(successes: int, sample_size: int, z: float = 1.959963984540054) -> tuple[float, float]:
    proportion = successes / sample_size
    denominator = 1 + (z * z / sample_size)
    centre = proportion + (z * z / (2 * sample_size))
    margin = z * math.sqrt((proportion * (1 - proportion) / sample_size) + (z * z / (4 * sample_size**2)))
    return (centre - margin) / denominator, (centre + margin) / denominator


def _point_biserial(rows: list[dict[str, Any]]) -> tuple[float | None, int, int]:
    correct_rest = [row["score"] - 1 for row in rows if row["is_correct"]]
    incorrect_rest = [row["score"] for row in rows if not row["is_correct"]]
    if not correct_rest or not incorrect_rest:
        return None, len(correct_rest), len(incorrect_rest)
    rest_scores = correct_rest + incorrect_rest
    mean = sum(rest_scores) / len(rest_scores)
    variance = sum((score - mean) ** 2 for score in rest_scores) / len(rest_scores)
    if variance <= 0:
        return None, len(correct_rest), len(incorrect_rest)
    p = len(correct_rest) / len(rows)
    q = 1 - p
    coefficient = (
        (sum(correct_rest) / len(correct_rest) - sum(incorrect_rest) / len(incorrect_rest))
        / math.sqrt(variance)
        * math.sqrt(p * q)
    )
    return coefficient, len(correct_rest), len(incorrect_rest)


def _distractor_shares(rows: list[dict[str, Any]]) -> list[float]:
    if not rows:
        return []
    correct_option = rows[0]["correct_option"]
    counts = {option: 0 for option in range(4) if option != correct_option}
    for row in rows:
        selected = row["selected_option"]
        if selected in counts:
            counts[selected] += 1
    return [count / len(rows) for count in counts.values()]


def _difficulty_mismatch(authored: str, facility: float) -> bool:
    return (
        (authored == "easy" and facility < 0.70)
        or (authored == "medium" and not 0.35 <= facility <= 0.80)
        or (authored == "hard" and facility > 0.55)
    )
