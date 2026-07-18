"""Independent, source-only verification pass for generated questions."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from config.settings import QUESTION_VERIFICATION_MIN_CONFIDENCE
from services.gemini_provider_pool import GeminiProviderPool
from services.question_validation import QuizValidationError
from services.source_grounding import GroundingBundle
from storage import verification_audits_repo

CHECK_FIELDS = (
    "correct_answer_supported",
    "options_distinct",
    "explanation_supported",
    "unambiguous",
    "fact_current",
    "micro_topic_match",
    "difficulty_match",
)

VERIFICATION_JSON_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "question_number": {"type": "INTEGER"},
            "verdict": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            **{name: {"type": "BOOLEAN"} for name in CHECK_FIELDS},
            "notes": {"type": "STRING"},
        },
        "required": ["question_number", "verdict", "confidence", *CHECK_FIELDS, "notes"],
    },
}


def verify_questions(
    questions: list[dict],
    bundle: GroundingBundle,
    pool: GeminiProviderPool,
    *,
    quiz_id: str | None = None,
) -> tuple[list[dict], dict]:
    prompt = _verification_prompt(questions, bundle)
    raw_text, metadata = pool.generate_subject_quiz(
        prompt=prompt,
        response_schema=VERIFICATION_JSON_SCHEMA,
    )
    try:
        raw = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError) as exc:
        _record_audit(
            quiz_id, questions, bundle, raw_text, raw_text, "rejected",
            ["malformed_verifier_json"], metadata,
        )
        raise QuizValidationError("Independent verifier returned malformed JSON.") from exc
    if not isinstance(raw, list) or len(raw) != len(questions):
        _record_audit(
            quiz_id, questions, bundle, raw, raw_text, "rejected",
            ["wrong_verifier_result_count"], metadata,
        )
        raise QuizValidationError("Independent verifier must return one result per question.")

    indexed: dict[int, dict] = {}
    for item in raw:
        if not isinstance(item, dict) or isinstance(item.get("question_number"), bool):
            _record_audit(
                quiz_id, questions, bundle, raw, raw_text, "rejected",
                ["invalid_verifier_result_object"], metadata,
            )
            raise QuizValidationError("Independent verifier returned an invalid result object.")
        number = item.get("question_number")
        if not isinstance(number, int) or number not in range(1, len(questions) + 1) or number in indexed:
            _record_audit(
                quiz_id, questions, bundle, raw, raw_text, "rejected",
                ["invalid_verifier_question_numbering"], metadata,
            )
            raise QuizValidationError("Independent verifier returned invalid question numbering.")
        indexed[number] = item

    verified_at = datetime.now(timezone.utc).isoformat()
    clean: list[dict] = []
    rejection_reasons: list[str] = []
    for number, question in enumerate(questions, start=1):
        result = indexed[number]
        confidence = result.get("confidence")
        checks_ok = all(result.get(name) is True for name in CHECK_FIELDS)
        if (
            result.get("verdict") != "verified"
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
            or float(confidence) < QUESTION_VERIFICATION_MIN_CONFIDENCE
            or not checks_ok
        ):
            reasons = [name for name in CHECK_FIELDS if result.get(name) is not True]
            rejection_reasons.append(
                f"question_{number}:" + (
                    ",".join(reasons) or str(result.get("notes") or "low_confidence")
                )
            )
            continue
        notes = str(result.get("notes") or "").strip()
        clean.append({
            **question,
            "verification_status": "verified",
            "verification_score": float(confidence),
            "verification_notes": notes or "All source-grounded checks passed.",
            "verification_checks": {name: True for name in CHECK_FIELDS},
            "verified_at": verified_at,
            "verification_model": metadata.get("model"),
        })
    if rejection_reasons:
        _record_audit(
            quiz_id, questions, bundle, raw, raw_text, "rejected",
            rejection_reasons, metadata,
        )
        raise QuizValidationError(
            "Independent verification rejected the quiz: " + "; ".join(rejection_reasons)
        )
    _record_audit(
        quiz_id, questions, bundle, raw, raw_text, "verified", [], metadata,
    )
    return clean, metadata


def _verification_prompt(questions: list[dict], bundle: GroundingBundle) -> str:
    review_rows = [
        {
            "question_number": index,
            "question": row["question"],
            "options": row["options"],
            "claimed_correct_index": row["correct_index"],
            "explanation": row["explanation"],
            "detailed_explanation": row["detailed_explanation"],
            "difficulty": row["difficulty"],
            "micro_topic_key": row["micro_topic_key"],
            "source_document_id": row["source_document_id"],
        }
        for index, row in enumerate(questions, start=1)
    ]
    return f"""Act as an independent competitive-exam MCQ verifier.
Use only the VERIFIED FACTS below. Do not rely on memory or add outside facts.
For every question, independently solve it and test every required boolean.
Return one JSON result for each numbered question. Use verdict \"verified\" only
when all booleans are true and confidence is at least {QUESTION_VERIFICATION_MIN_CONFIDENCE:.2f};
otherwise use verdict \"rejected\" and explain the failure in notes.

Canonical subject: {bundle.subject_key}
Chapter: {bundle.chapter}
Micro-topic: {bundle.micro_topic_key} — {bundle.micro_topic_name}
VERIFIED FACTS:
{json.dumps(bundle.prompt_facts(), ensure_ascii=False, separators=(',', ':'))}
QUESTIONS TO VERIFY:
{json.dumps(review_rows, ensure_ascii=False, separators=(',', ':'))}
"""


def _record_audit(
    quiz_id: str | None,
    questions: list[dict],
    bundle: GroundingBundle,
    verifier_output: object,
    verifier_raw_text: str,
    verdict: str,
    rejection_reasons: list[str],
    metadata: dict,
) -> None:
    if not quiz_id:
        return
    verification_audits_repo.record(
        quiz_id=quiz_id,
        subject_key=bundle.subject_key,
        chapter=bundle.chapter,
        micro_topic_id=bundle.micro_topic_id,
        source_document_ids=sorted(bundle.source_ids),
        generated_questions=questions,
        verifier_output=verifier_output,
        verifier_raw_text=verifier_raw_text,
        verdict=verdict,
        rejection_reasons=rejection_reasons,
        verifier_provider=metadata.get("provider"),
        verifier_model=metadata.get("model"),
    )
