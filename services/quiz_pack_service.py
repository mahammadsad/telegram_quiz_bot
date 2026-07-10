"""Quiz-pack business logic on top of repo_1's shared database schema."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from config.settings import (
    BOT_TYPE,
    GEMINI_MODEL,
    QUIZ_PACK_SOURCE_PREFIX,
    SCHEDULER_MAX_REUSE_GAP_DAYS,
    SCHEDULER_MIN_REUSE_GAP_DAYS,
    SESSION_TYPE,
    SIMILARITY_THRESHOLD,
    TELEGRAM_DETAILED_EXPLANATION_LIMIT,
    TELEGRAM_EXPLANATION_LIMIT,
    TELEGRAM_OPTION_LIMIT,
    TELEGRAM_QUESTION_LIMIT,
)
from config.subjects import SUBJECTS
from models.attempt import Attempt
from models.poll import Poll
from models.question import Question
from models.user import User
from storage import attempts_repo, polls_repo, questions_repo, stats_repo, submissions_repo, users_repo
from services.question_validation import QUESTION_COUNT, validate_questions
from utils.quiz_ids import parse_quiz_id
from utils.hashing import normalize_text, question_hash
from utils.iso_week import iso_week_number

LOG = logging.getLogger("services.quiz_pack")
OPTION_LETTERS = "ABCD"


def quiz_source(quiz_id: str) -> str:
    return f"{QUIZ_PACK_SOURCE_PREFIX}{quiz_id}"


def session_id_for_quiz(quiz_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wb-exam-quiz-pack:{quiz_id}"))


def get_quiz_pack(quiz_id: str) -> dict | None:
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

    first_question = items[0]["question"]
    try:
        quiz_date, subject_key = parse_quiz_id(quiz_id)
    except ValueError:
        quiz_date, subject_key = date.today(), None
    configured = SUBJECTS.get(subject_key or "")
    return {
        "quiz_id": quiz_id,
        "session_id": deliveries[0]["session_id"],
        "meta": {
            "quiz_id": quiz_id,
            "subject_key": subject_key,
            "subject": configured.telegram_display_name if configured else first_question.get("subject") or "",
            "chapter": first_question.get("topic") or "",
            "date": quiz_date.isoformat() if quiz_date else _date_from_quiz_id(quiz_id),
        },
        "items": items,
    }


def record_quiz_pack(quiz_id: str, raw_questions: list[dict], meta: dict, chat_id: int = 0) -> dict:
    existing = get_quiz_pack(quiz_id)
    if existing:
        LOG.info("Quiz pack %s already exists in Supabase; reusing it.", quiz_id)
        return existing

    subject_key = str(meta.get("subject_key") or meta.get("subject") or "").strip()
    chapter = str(meta.get("chapter") or "").strip()
    clean_questions = validate_questions(raw_questions, subject_key, chapter)
    session_id = session_id_for_quiz(quiz_id)
    rows: list[dict] = []
    for index, item in enumerate(clean_questions):
        question_row = _get_or_insert_question(quiz_id, item, meta)
        delivery = Poll(
            telegram_poll_id=f"miniapp:{quiz_id}:{index + 1}",
            telegram_message_id=index + 1,
            telegram_chat_id=chat_id,
            question_id=question_row["id"],
            session_id=session_id,
            bot_type=BOT_TYPE,
            run_slot=quiz_id,
        )
        poll_row = polls_repo.upsert_poll(delivery)
        rows.append({"poll": poll_row, "question": question_row})

    LOG.info("Recorded quiz pack %s with %d question delivery rows.", quiz_id, len(rows))
    return {
        "quiz_id": quiz_id,
        "session_id": session_id,
        "meta": {
            "quiz_id": quiz_id,
            "subject_key": subject_key,
            "subject": meta.get("subject_display_name") or meta.get("subject", ""),
            "chapter": meta.get("chapter", ""),
            "date": meta.get("date") or _date_from_quiz_id(quiz_id),
        },
        "items": rows,
    }


def mark_pack_posted(pack: dict) -> None:
    for item in pack.get("items", []):
        question = item["question"]
        questions_repo.mark_used(
            question_id=question["id"],
            usage_count=question.get("usage_count", 0),
            min_gap_days=SCHEDULER_MIN_REUSE_GAP_DAYS,
            max_gap_days=SCHEDULER_MAX_REUSE_GAP_DAYS,
        )


def public_quiz_payload(pack: dict) -> dict:
    return {
        "meta": pack["meta"],
        "qs": [
            {
                "q": item["question"]["question_text"],
                "o": [
                    item["question"]["option_a"],
                    item["question"]["option_b"],
                    item["question"]["option_c"],
                    item["question"]["option_d"],
                ],
            }
            for item in pack["items"]
        ],
    }


def submit_quiz_attempts(quiz_id: str, telegram_user: dict, answers: list[int | None]) -> dict:
    pack = get_quiz_pack(quiz_id)
    if not pack:
        raise ValueError("Quiz pack was not found.")

    items = pack["items"]
    if len(items) != QUESTION_COUNT:
        raise ValueError("Quiz data is incomplete; submission is disabled.")
    _validate_answers(answers)
    user_row = users_repo.upsert_user(User.from_telegram(telegram_user))
    existing_submission = submissions_repo.get(quiz_id, user_row["id"])
    if existing_submission:
        if existing_submission.get("answers") != answers:
            raise ValueError("This quiz has already been submitted; completed attempts are immutable.")
        return _submission_result(quiz_id, items, answers, existing_submission)

    for index, selected_index in enumerate(answers):
        if selected_index is None:
            continue

        item = items[index]
        question = item["question"]
        poll = item["poll"]
        selected_option = OPTION_LETTERS[selected_index]
        attempts_repo.insert_attempt(Attempt(
            user_id=user_row["id"],
            question_id=question["id"],
            poll_id=poll["id"],
            selected_option=selected_option,
            is_correct=selected_option == question["correct_option"],
            response_time_seconds=None,
            session_type=SESSION_TYPE,
        ))

    score = sum(
        selected is not None and OPTION_LETTERS[selected] == item["question"]["correct_option"]
        for item, selected in zip(items, answers)
    )
    submission_payload = {
        "quiz_id": quiz_id,
        "user_id": user_row["id"],
        "answers": answers,
        "score": score,
        "total": QUESTION_COUNT,
        "answered": sum(value is not None for value in answers),
    }
    try:
        submission = submissions_repo.insert(submission_payload)
    except Exception:
        # A simultaneous identical browser retry may win the unique
        # (quiz_id,user_id) race after the initial lookup.
        submission = submissions_repo.get(quiz_id, user_row["id"])
        if not submission or submission.get("answers") != answers:
            raise
    return _submission_result(quiz_id, items, answers, submission)


def _validate_answers(answers: list[int | None]) -> None:
    if not isinstance(answers, list) or len(answers) != QUESTION_COUNT:
        raise ValueError("answers must contain exactly 10 entries.")
    for value in answers:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value not in range(4)):
            raise ValueError("Each answer must be 0, 1, 2, 3, or null.")


def _submission_result(quiz_id: str, items: list[dict], answers: list[int | None], submission: dict) -> dict:
    review = []
    for item, selected_index in zip(items, answers):
        question = item["question"]
        correct_index = OPTION_LETTERS.index(question["correct_option"])
        review.append({
            "q": question["question_text"],
            "o": [question["option_a"], question["option_b"], question["option_c"], question["option_d"]],
            "selectedIndex": selected_index,
            "correctIndex": correct_index,
            "isCorrect": selected_index is not None and selected_index == correct_index,
            "explanation": question.get("detailed_explanation") or question.get("explanation") or "",
        })
    board = stats_repo.quiz_leaderboard(quiz_id, limit=100)
    same = submissions_repo.list_for_quiz(quiz_id, limit=10000)
    same.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("completed_at") or ""), str(row.get("user_id") or "")))
    user_rank = next((i + 1 for i, row in enumerate(same) if row.get("user_id") == submission.get("user_id")), None)
    return {
        "quiz_id": quiz_id,
        "score": int(submission.get("score") or 0),
        "total": QUESTION_COUNT,
        "answered": int(submission.get("answered") or sum(value is not None for value in answers)),
        "rank": user_rank,
        "participants": board["participants"],
        "review": review,
    }


def _get_or_insert_question(quiz_id: str, item: dict, meta: dict) -> dict:
    question = _build_question(quiz_id, item, meta)

    exact = questions_repo.get_by_hash_any_bot(question.question_hash)
    if exact:
        if exact.get("subject") != question.subject or exact.get("topic") != question.topic:
            raise ValueError(f"Question classification collision in {quiz_id}; refusing cross-subject reuse.")
        LOG.info("Quiz %s reused exact duplicate question %s.", quiz_id, exact["id"])
        return exact

    similar = questions_repo.find_similar(
        question.normalized_text,
        bot_type=BOT_TYPE,
        threshold=SIMILARITY_THRESHOLD,
        limit=1,
    )
    if similar:
        row = questions_repo.get_by_id(similar[0]["id"])
        if row:
            if row.get("subject") != question.subject or row.get("topic") != question.topic:
                raise ValueError(f"Similar question classification mismatch in {quiz_id}.")
            LOG.info("Quiz %s reused similar question %s.", quiz_id, row["id"])
            return row

    return questions_repo.insert_question(question)


def _build_question(quiz_id: str, item: dict, meta: dict) -> Question:
    question_text = _str(item.get("question", item.get("q")))
    options = [_str(option) for option in item.get("options", item.get("o", []))]
    if len(options) != 4 or not question_text or any(not option for option in options):
        raise ValueError(f"Invalid quiz question in {quiz_id}: expected question text and 4 options.")

    correct_index = int(item.get("correct_index", item.get("a")))
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
    )


def _date_from_quiz_id(quiz_id: str) -> str:
    try:
        return parse_quiz_id(quiz_id)[0].isoformat()
    except ValueError:
        pass
    return date.today().isoformat()


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()
