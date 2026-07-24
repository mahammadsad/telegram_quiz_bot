"""Quiz-pack business logic on top of repo_1's shared database schema."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from config.settings import (
    BOT_TYPE,
    GEMINI_MODEL,
    QUESTION_REPORT_THRESHOLD,
    QUIZ_PACK_SOURCE_PREFIX,
    SCHEDULER_MAX_REUSE_GAP_DAYS,
    SCHEDULER_MIN_REUSE_GAP_DAYS,
    SIMILARITY_THRESHOLD,
)
from config.subjects import SUBJECTS
from errors import DatabaseIntegrityError
from models.question import Question
from models.user import User
from services.question_validation import (
    QUESTION_COUNT,
    checksum_for_pack,
    content_checksum,
    validate_questions,
)
from storage import (
    polls_repo,
    question_reports_repo,
    questions_repo,
    quiz_attempts_repo,
    quiz_packs_repo,
    quiz_runs_repo,
    source_documents_repo,
    users_repo,
)
from utils.hashing import normalize_text, question_content_hash, question_hash
from utils.iso_week import iso_week_number
from utils.quiz_ids import parse_quiz_id

LOG = logging.getLogger("services.quiz_pack")
OPTION_LETTERS = "ABCD"
REPORT_REASONS = {
    "wrong_answer",
    "multiple_correct",
    "ambiguous",
    "incorrect_explanation",
    "language_spelling",
    "outdated",
    "outside_syllabus",
    "broken_source",
    "other",
}


def quiz_source(quiz_id: str) -> str:
    return f"{QUIZ_PACK_SOURCE_PREFIX}{quiz_id}"


def session_id_for_quiz(quiz_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wb-exam-quiz-pack:{quiz_id}"))


def get_quiz_pack(quiz_id: str) -> dict | None:
    mappings = quiz_packs_repo.list_questions(quiz_id)
    if mappings:
        mapped_items = []
        for mapping in mappings:
            question = mapping.get("questions") or {}
            if isinstance(question, list):
                question = question[0] if question else {}
            if not question:
                raise DatabaseIntegrityError(
                    f"Quiz {quiz_id} has an ordered mapping without a question."
                )
            mapped_items.append({"mapping": mapping, "question": question})
        return _pack_from_items(quiz_id, mapped_items)

    # Historical compatibility: migration 004 backfills these simulated poll
    # rows into quiz_questions, but the read path remains available during a
    # rolling deployment and for old databases awaiting the migration.
    deliveries = polls_repo.get_by_run_slot(quiz_id, bot_type=BOT_TYPE)
    if not deliveries:
        return None

    items: list[dict] = []
    for delivery in deliveries:
        question = questions_repo.get_by_id(delivery["question_id"])
        if not question:
            LOG.warning("Quiz %s references missing question_id=%s", quiz_id, delivery["question_id"])
            continue
        items.append({"poll": delivery, "question": question})

    if not items:
        return None

    return _pack_from_items(quiz_id, items, session_id=deliveries[0]["session_id"])


def get_ready_quiz_pack(quiz_id: str) -> dict | None:
    """Return only a complete pack whose saved database content is certified."""
    run = quiz_runs_repo.get(quiz_id)
    if (
        not run
        or run.get("status") not in {"ready", "posting", "posting_failed", "posted"}
        or run.get("integrity_verified") is not True
        or int(run.get("checksum_contract_version") or 0) != 2
        or not run.get("generated_checksum")
        or run.get("generated_checksum") != run.get("persisted_checksum")
    ):
        return None
    pack = get_quiz_pack(quiz_id)
    if not pack or len(pack.get("items") or []) != QUESTION_COUNT:
        return None
    if checksum_for_pack(pack) != run["persisted_checksum"]:
        LOG.error("QUIZ_READ_BLOCKED checksum_mismatch quiz_id=%s", quiz_id)
        return None
    return pack


def _pack_from_items(quiz_id: str, items: list[dict], session_id: str | None = None) -> dict:
    first_question = items[0]["question"]
    try:
        quiz_date, subject_key = parse_quiz_id(quiz_id)
    except ValueError:
        quiz_date, subject_key = date.today(), None
    configured = SUBJECTS.get(subject_key or "")
    return {
        "quiz_id": quiz_id,
        "session_id": session_id or session_id_for_quiz(quiz_id),
        "meta": {
            "quiz_id": quiz_id,
            "subject_key": subject_key,
            "subject": configured.telegram_display_name if configured else first_question.get("subject") or "",
            "chapter": first_question.get("topic") or "",
            "micro_topic": first_question.get("micro_topic_key") or "",
            "date": quiz_date.isoformat() if quiz_date else _date_from_quiz_id(quiz_id),
        },
        "items": items,
    }


def record_quiz_pack(
    quiz_id: str,
    raw_questions: list[dict],
    meta: dict,
    chat_id: int = 0,
    *,
    worker_id: str,
    replace: bool = False,
) -> dict:
    subject_key = str(meta.get("subject_key") or meta.get("subject") or "").strip()
    chapter = str(meta.get("chapter") or "").strip()
    clean_questions = validate_questions(raw_questions, subject_key, chapter)
    question_rows = [_question_row_for_atomic_save(quiz_id, item, meta) for item in clean_questions]
    checksum = content_checksum(quiz_id, subject_key, chapter, clean_questions)
    save_result = quiz_packs_repo.save_atomic(
        quiz_id=quiz_id,
        worker_id=worker_id,
        questions=question_rows,
        content_checksum=checksum,
        replace=replace,
    )
    if not save_result.get("ready"):
        raise DatabaseIntegrityError(
            "Saved quiz checksum did not match generated content; posting is blocked."
        )
    saved = get_quiz_pack(quiz_id)
    if not saved or len(saved.get("items") or []) != QUESTION_COUNT:
        raise DatabaseIntegrityError("Atomic quiz save did not produce a complete readable pack.")
    readback_checksum = content_checksum(
        quiz_id,
        subject_key,
        chapter,
        [_content_row_from_saved_item(item) for item in saved["items"]],
    )
    if (
        readback_checksum != checksum
        or readback_checksum != save_result.get("persisted_checksum")
    ):
        quiz_packs_repo.record_readback_integrity_failure(
            quiz_id=quiz_id,
            worker_id=worker_id,
            generated_checksum=checksum,
            persisted_checksum=readback_checksum,
            question_ids=[str(item["question"]["id"]) for item in saved["items"]],
        )
        raise DatabaseIntegrityError(
            "Quiz read-back checksum did not match generated content; posting is blocked."
        )
    LOG.info("Recorded and checksum-verified quiz pack %s with 10 immutable versions.", quiz_id)
    return saved


def mark_pack_posted(pack: dict) -> None:
    used_at = datetime.now(timezone.utc).isoformat()
    micro_topic_ids: set[str] = set()
    for item in pack.get("items", []):
        question = item["question"]
        questions_repo.mark_used(
            question_id=question["id"],
            usage_count=question.get("usage_count", 0),
            min_gap_days=SCHEDULER_MIN_REUSE_GAP_DAYS,
            max_gap_days=SCHEDULER_MAX_REUSE_GAP_DAYS,
        )
        if question.get("micro_topic_id"):
            micro_topic_ids.add(str(question["micro_topic_id"]))
    for micro_topic_id in micro_topic_ids:
        source_documents_repo.mark_micro_topic_used(micro_topic_id, used_at)


def public_quiz_payload(pack: dict) -> dict:
    return {
        "meta": pack["meta"],
        "capabilities": {"submission": True, "source": "api"},
        "qs": [
            {
                "q": item["question"]["question_text"],
                "o": [
                    item["question"]["option_a"],
                    item["question"]["option_b"],
                    item["question"]["option_c"],
                    item["question"]["option_d"],
                ],
                "subjectKey": pack["meta"].get("subject_key") or item["question"].get("subject") or "",
                "chapter": item["question"].get("topic") or pack["meta"].get("chapter") or "",
                "microTopicKey": item["question"].get("micro_topic_key") or "",
            }
            for item in pack["items"]
        ],
    }


def submit_quiz_attempts(
    quiz_id: str,
    telegram_user: dict,
    answers: list[int | None],
    attempt_id: uuid.UUID,
    duration_seconds: int | None = None,
    response_times: list[float | None] | None = None,
    marked_for_review: list[bool] | None = None,
) -> dict:
    pack = get_ready_quiz_pack(quiz_id)
    if not pack:
        raise ValueError("Quiz pack is not ready for submission.")

    items = pack["items"]
    if len(items) != QUESTION_COUNT:
        raise ValueError("Quiz data is incomplete; submission is disabled.")
    _validate_answers(answers)
    if not isinstance(attempt_id, uuid.UUID):
        raise ValueError("A valid client-generated UUID attemptId is required.")
    user_row = users_repo.upsert_user(User.from_telegram(telegram_user))
    return quiz_attempts_repo.submit_atomic(
        quiz_id=quiz_id,
        user_id=user_row["id"],
        client_attempt_id=attempt_id,
        answers=answers,
        duration_seconds=duration_seconds,
        response_times=response_times,
        marked_for_review=marked_for_review,
    )


def get_quiz_attempt_result(
    *,
    quiz_id: str,
    telegram_user: dict,
    client_attempt_id: uuid.UUID,
) -> dict | None:
    """Recover one completed result using authenticated user ownership."""
    if not isinstance(client_attempt_id, uuid.UUID):
        raise ValueError("A valid client-generated UUID attemptId is required.")
    user_row = users_repo.upsert_user(User.from_telegram(telegram_user))
    return quiz_attempts_repo.get_result_for_client(
        quiz_id=quiz_id,
        user_id=user_row["id"],
        client_attempt_id=client_attempt_id,
    )


def submit_question_report(
    *,
    question_id: str,
    quiz_id: str,
    telegram_user: dict,
    client_attempt_id: uuid.UUID,
    reason: str,
    details: str,
) -> dict:
    if reason not in REPORT_REASONS:
        raise ValueError("Invalid report reason.")
    clean_details = details.strip()
    if len(clean_details) > 1000:
        raise ValueError("Report details must be 1000 characters or fewer.")
    if reason == "other" and not clean_details:
        raise ValueError("Other reports require details.")
    user_row = users_repo.upsert_user(User.from_telegram(telegram_user))
    return question_reports_repo.submit(
        question_id=question_id,
        quiz_id=quiz_id,
        user_id=user_row["id"],
        client_attempt_id=str(client_attempt_id),
        reason=reason,
        details=clean_details,
        threshold=QUESTION_REPORT_THRESHOLD,
    )


def _validate_answers(answers: list[int | None]) -> None:
    if not isinstance(answers, list) or len(answers) != QUESTION_COUNT:
        raise ValueError("answers must contain exactly 10 entries.")
    for value in answers:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value not in range(4)):
            raise ValueError("Each answer must be 0, 1, 2, 3, or null.")


def _build_question(quiz_id: str, item: dict, meta: dict) -> Question:
    question_text = _str(item.get("question", item.get("q")))
    options = [_str(option) for option in item.get("options", item.get("o", []))]
    if len(options) != 4 or not question_text or any(not option for option in options):
        raise ValueError(f"Invalid quiz question in {quiz_id}: expected question text and 4 options.")

    raw_correct_index = item.get("correct_index", item.get("a"))
    if raw_correct_index is None:
        raise ValueError(f"Invalid correct option in {quiz_id}: missing value")
    correct_index = int(raw_correct_index)
    if not (0 <= correct_index <= 3):
        raise ValueError(f"Invalid correct option in {quiz_id}: {correct_index}")

    explanation = _str(item.get("explanation", item.get("e")))
    detailed = _str(item.get("detailed_explanation", explanation))
    subject = _str(meta.get("subject_key") or item.get("subject_key") or item.get("subject"))
    topic = _str(meta.get("chapter") or item.get("topic") or item.get("subtopic") or "General")[:150]
    normalized = normalize_text(question_text)

    return Question(
        question_text=question_text,
        option_a=options[0],
        option_b=options[1],
        option_c=options[2],
        option_d=options[3],
        correct_option=OPTION_LETTERS[correct_index],
        explanation=explanation or "N/A",
        detailed_explanation=detailed or explanation or "বিস্তারিত ব্যাখ্যা উপলব্ধ নেই।",
        subject=subject,
        topic=topic,
        difficulty=_str(item.get("difficulty") or "medium"),
        gemini_model=_str(meta.get("generation_model") or GEMINI_MODEL),
        source=quiz_source(quiz_id),
        week_number=iso_week_number(),
        bot_type=BOT_TYPE,
        question_hash=question_hash(question_text),
        normalized_text=normalized,
        status="active",
        micro_topic_id=_str(item.get("micro_topic_id")),
        micro_topic_key=_str(item.get("micro_topic_key")),
        source_document_id=_str(item.get("source_document_id")),
        verification_status=_str(item.get("verification_status")),
        verification_score=item.get("verification_score"),
        verification_notes=_str(item.get("verification_notes")),
        verification_checks=item.get("verification_checks") if isinstance(item.get("verification_checks"), dict) else {},
        verified_at=_str(item.get("verified_at")) or None,
        verification_model=_str(item.get("verification_model")) or None,
        stem_hash=_str(item.get("stem_hash")) or question_hash(question_text),
        content_hash=_str(item.get("content_hash")) or question_content_hash(item),
        language=_str(item.get("language")) or ("bn-en" if subject == "english" else "bn"),
        source_url=_str(item.get("source_url")) or None,
        source_title=_str(item.get("source_title")) or None,
        source_domain=_str(item.get("source_domain")) or None,
        source_kind=_str(item.get("source_kind")) or None,
        source_published_at=_str(item.get("source_published_at")) or None,
        source_accessed_at=_str(item.get("source_accessed_at")) or None,
        evidence_summary=_str(item.get("evidence_summary")) or None,
        fact_version=_str(item.get("fact_version")) or None,
        expires_at=_str(item.get("expires_at")) or None,
        review_required=False,
    )


def _question_row_for_atomic_save(quiz_id: str, item: dict, meta: dict) -> dict:
    """Reuse only byte-equivalent content; never substitute an unverified near-duplicate."""
    question = _build_question(quiz_id, item, meta)
    row = question.to_insert_dict()
    if not question.content_hash:
        raise DatabaseIntegrityError(f"Question content hash is missing in {quiz_id}.")
    exact = questions_repo.get_by_content_hash(question.content_hash)
    if exact:
        if exact.get("subject") != question.subject or exact.get("topic") != question.topic:
            raise DatabaseIntegrityError(f"Exact question classification mismatch in {quiz_id}.")
        row["reuse_question_id"] = exact["id"]
        return row
    same_stem = questions_repo.get_latest_by_stem(question.stem_hash or question.question_hash)
    if same_stem:
        # A changed answer, choice, explanation, source, or verification record
        # is a new immutable version, not a fuzzy duplicate.
        return row
    similar = questions_repo.find_similar(
        question.normalized_text,
        bot_type=BOT_TYPE,
        threshold=SIMILARITY_THRESHOLD,
        limit=1,
    )
    if not similar:
        return row
    raise DatabaseIntegrityError(
        f"Near-duplicate question detected in {quiz_id}; regenerate instead of substituting content."
    )


def _content_row_from_saved_item(item: dict) -> dict:
    question = item.get("question") or {}
    return {
        "question_text": question.get("question_text"),
        "option_a": question.get("option_a"),
        "option_b": question.get("option_b"),
        "option_c": question.get("option_c"),
        "option_d": question.get("option_d"),
        "correct_option": question.get("correct_option"),
        "explanation": question.get("explanation"),
        "detailed_explanation": question.get("detailed_explanation"),
        "subject": question.get("subject"),
        "topic": question.get("topic"),
        "micro_topic_key": question.get("micro_topic_key"),
        "difficulty": question.get("difficulty"),
        "language": question.get("language"),
        "source_document_id": question.get("source_document_id"),
        "source_url": question.get("source_url"),
        "source_title": question.get("source_title"),
        "source_domain": question.get("source_domain"),
        "source_kind": question.get("source_kind"),
        "source_published_at": question.get("source_published_at"),
        "source_accessed_at": question.get("source_accessed_at"),
        "evidence_summary": question.get("evidence_summary"),
        "fact_version": question.get("fact_version"),
        "verification_status": question.get("verification_status"),
        "verification_score": question.get("verification_score"),
        "verification_notes": question.get("verification_notes"),
        "verified_at": question.get("verified_at"),
        "verification_model": question.get("verification_model"),
    }


def _date_from_quiz_id(quiz_id: str) -> str:
    try:
        return parse_quiz_id(quiz_id)[0].isoformat()
    except ValueError:
        pass
    return date.today().isoformat()


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()
