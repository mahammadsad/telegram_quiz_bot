"""Strict validation and deterministic checksums for generated quiz content."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from typing import Any

from config.settings import QUESTION_VERIFICATION_MIN_CONFIDENCE, QUIZ_DIFFICULTY_DISTRIBUTION
from utils.hashing import normalize_text, question_hash

QUESTION_COUNT = 10
_BENGALI_RE = re.compile(r"[\u0980-\u09ff]")
_DIFFICULTIES = {"easy", "medium", "hard"}


class QuizValidationError(ValueError):
    pass


def validate_questions(
    raw_questions: list[dict],
    subject_key: str,
    chapter: str,
    *,
    enforce_composition: bool = True,
    micro_topic_id: str | None = None,
    micro_topic_key: str | None = None,
    allowed_source_ids: set[str] | None = None,
    require_verification: bool = True,
) -> list[dict]:
    if not isinstance(raw_questions, list) or len(raw_questions) != QUESTION_COUNT:
        count = len(raw_questions) if isinstance(raw_questions, list) else 0
        raise QuizValidationError(f"A quiz must contain exactly 10 questions; received {count}.")

    clean: list[dict] = []
    seen_questions: set[str] = set()
    expected_topic_id = _text(micro_topic_id)
    expected_topic_key = _text(micro_topic_key)
    for number, raw in enumerate(raw_questions, start=1):
        if not isinstance(raw, dict):
            raise QuizValidationError(f"Question {number} must be an object.")
        text = _text(raw.get("question", raw.get("q")))
        options_raw = raw.get("options", raw.get("o"))
        if not isinstance(options_raw, list):
            raise QuizValidationError(f"Question {number} must contain four options.")
        options = [_text(option) for option in options_raw]
        explanation = _text(raw.get("explanation", raw.get("e")))
        detailed = _text(raw.get("detailed_explanation", raw.get("detailedExplanation")))
        difficulty = _text(raw.get("difficulty") or "medium").lower()
        raw_subject = _text(raw.get("subject_key") or raw.get("subject") or subject_key)
        raw_chapter = _text(raw.get("chapter") or chapter)
        raw_micro_topic_id = _text(raw.get("micro_topic_id"))
        raw_micro_topic_key = _text(raw.get("micro_topic_key"))
        source_document_id = _text(raw.get("source_document_id"))
        correct = raw.get("correct_index", raw.get("a"))

        if not text or not _BENGALI_RE.search(text) and subject_key != "english":
            raise QuizValidationError(f"Question {number} must contain readable Bengali text.")
        if text.endswith(("...", "…")):
            raise QuizValidationError(f"Question {number} appears truncated.")
        if len(options) != 4 or any(not option for option in options):
            raise QuizValidationError(f"Question {number} must contain exactly four non-empty options.")
        normalized_options = [normalize_text(option) for option in options]
        if len(set(normalized_options)) != 4:
            raise QuizValidationError(f"Question {number} contains duplicate options.")
        if isinstance(correct, bool) or not isinstance(correct, int) or correct not in range(4):
            raise QuizValidationError(f"Question {number} has an invalid correct index.")
        normalized_answer = normalized_options[correct]
        if subject_key not in {"mathematics", "reasoning"} and len(normalized_answer) >= 4 and normalized_answer in normalize_text(text):
            raise QuizValidationError(f"Question {number} reveals its correct answer.")
        if not explanation or not detailed or not _BENGALI_RE.search(explanation + detailed):
            raise QuizValidationError(f"Question {number} must contain Bengali explanations.")
        if raw_subject != subject_key:
            raise QuizValidationError(f"Question {number} belongs to another subject.")
        if raw_chapter != chapter:
            raise QuizValidationError(f"Question {number} belongs to another chapter.")
        if not raw_micro_topic_id or not _is_uuid(raw_micro_topic_id):
            raise QuizValidationError(f"Question {number} must contain a normalized micro-topic id.")
        if not raw_micro_topic_key:
            raise QuizValidationError(f"Question {number} must contain a reusable micro-topic key.")
        if not expected_topic_id:
            expected_topic_id = raw_micro_topic_id
        if not expected_topic_key:
            expected_topic_key = raw_micro_topic_key
        if raw_micro_topic_id != expected_topic_id or raw_micro_topic_key != expected_topic_key:
            raise QuizValidationError(f"Question {number} belongs to another micro-topic.")
        if not source_document_id or not _is_uuid(source_document_id):
            raise QuizValidationError(f"Question {number} must cite a verified source document.")
        if allowed_source_ids is not None and source_document_id not in allowed_source_ids:
            raise QuizValidationError(f"Question {number} cites a source outside the grounding bundle.")
        if difficulty not in _DIFFICULTIES:
            raise QuizValidationError(f"Question {number} has an invalid difficulty.")

        verification_status = _text(raw.get("verification_status"))
        verification_notes = _text(raw.get("verification_notes"))
        verification_score = raw.get("verification_score")
        verified_at = _text(raw.get("verified_at"))
        if require_verification:
            if verification_status != "verified":
                raise QuizValidationError(f"Question {number} was not independently verified.")
            if (
                isinstance(verification_score, bool)
                or not isinstance(verification_score, (int, float))
                or not 0 <= float(verification_score) <= 1
                or float(verification_score) < QUESTION_VERIFICATION_MIN_CONFIDENCE
            ):
                raise QuizValidationError(f"Question {number} has an invalid verification score.")
            if not verification_notes or not verified_at:
                raise QuizValidationError(f"Question {number} is missing verification evidence.")

        normalized_question = normalize_text(text)
        if not normalized_question or normalized_question in seen_questions:
            raise QuizValidationError(f"Question {number} is blank or duplicated.")
        seen_questions.add(normalized_question)

        clean.append({
            "question": text,
            "options": options,
            "correct_index": correct,
            "explanation": explanation,
            "detailed_explanation": detailed,
            "subject_key": subject_key,
            "chapter": chapter,
            "micro_topic_id": raw_micro_topic_id,
            "micro_topic_key": raw_micro_topic_key,
            "source_document_id": source_document_id,
            "difficulty": difficulty,
            "question_id": _text(raw.get("question_id")) or question_hash(text),
            "verification_status": verification_status or "generated",
            "verification_score": float(verification_score) if isinstance(verification_score, (int, float)) and not isinstance(verification_score, bool) else None,
            "verification_notes": verification_notes,
            "verification_checks": raw.get("verification_checks") if isinstance(raw.get("verification_checks"), dict) else {},
            "verified_at": verified_at or None,
            "verification_model": _text(raw.get("verification_model")) or None,
        })
    if enforce_composition:
        _validate_quiz_composition(clean)
    return clean


def _validate_quiz_composition(questions: list[dict]) -> None:
    difficulty_counts = Counter(item["difficulty"] for item in questions)
    if difficulty_counts != Counter(QUIZ_DIFFICULTY_DISTRIBUTION):
        expected = ", ".join(
            f"{count} {difficulty}" for difficulty, count in QUIZ_DIFFICULTY_DISTRIBUTION.items()
        )
        raise QuizValidationError(f"Quiz difficulty distribution must be {expected}.")

    position_counts = Counter(item["correct_index"] for item in questions)
    if sorted(position_counts.values()) != [2, 2, 3, 3] or set(position_counts) != set(range(4)):
        raise QuizValidationError("Correct answers must be balanced across all four option positions.")


def content_checksum(quiz_id: str, subject_key: str, chapter: str, questions: list[dict]) -> str:
    normalized = {
        "quiz_id": quiz_id,
        "subject_key": subject_key,
        "chapter": normalize_text(chapter),
        "questions": [
            {
                "question": normalize_text(item.get("question", item.get("q", ""))),
                "options": [normalize_text(value) for value in item.get("options", item.get("o", []))],
                "correct_index": item.get("correct_index", item.get("a")),
                "micro_topic_key": _text(item.get("micro_topic_key")),
                "source_document_id": _text(item.get("source_document_id")),
            }
            for item in questions
        ],
    }
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def checksum_for_pack(pack: dict) -> str:
    meta = pack.get("meta") or {}
    questions = []
    for item in pack.get("items") or []:
        row = item.get("question") or {}
        questions.append({
            "question": row.get("question_text"),
            "options": [row.get("option_a"), row.get("option_b"), row.get("option_c"), row.get("option_d")],
            "correct_index": "ABCD".find(str(row.get("correct_option") or "")),
            "micro_topic_key": row.get("micro_topic_key"),
            "source_document_id": row.get("source_document_id"),
        })
    return content_checksum(pack.get("quiz_id") or meta.get("quiz_id") or "", meta.get("subject_key") or meta.get("subject") or "", meta.get("chapter") or "", questions)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
