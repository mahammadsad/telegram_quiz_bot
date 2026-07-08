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
from models.attempt import Attempt
from models.poll import Poll
from models.question import Question
from models.user import User
from storage import attempts_repo, polls_repo, questions_repo, users_repo
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
    return {
        "quiz_id": quiz_id,
        "session_id": deliveries[0]["session_id"],
        "meta": {
            "quiz_id": quiz_id,
            "subject": first_question.get("subject") or "",
            "chapter": first_question.get("topic") or "",
            "date": _date_from_quiz_id(quiz_id),
        },
        "items": items,
    }


def record_quiz_pack(quiz_id: str, raw_questions: list[dict], meta: dict, chat_id: int = 0) -> dict:
    existing = get_quiz_pack(quiz_id)
    if existing:
        LOG.info("Quiz pack %s already exists in Supabase; reusing it.", quiz_id)
        return existing

    session_id = session_id_for_quiz(quiz_id)
    rows: list[dict] = []
    for index, item in enumerate(raw_questions):
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
            "subject": meta.get("subject", ""),
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

    user_row = users_repo.upsert_user(User.from_telegram(telegram_user))
    items = pack["items"]

    for index, selected_index in enumerate(answers[:len(items)]):
        if selected_index is None:
            continue
        if not isinstance(selected_index, int) or not (0 <= selected_index <= 3):
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

    persisted_attempts = attempts_repo.get_for_user_by_poll_ids(
        user_row["id"], [item["poll"]["id"] for item in items]
    )
    attempts_by_poll = {row["poll_id"]: row for row in persisted_attempts}

    review = []
    score = 0
    for item in items:
        question = item["question"]
        poll = item["poll"]
        attempt = attempts_by_poll.get(poll["id"])
        selected_option = attempt["selected_option"] if attempt else None
        selected_index = OPTION_LETTERS.index(selected_option) if selected_option in OPTION_LETTERS else None
        correct_index = OPTION_LETTERS.index(question["correct_option"])
        is_correct = bool(attempt and attempt.get("is_correct"))
        if is_correct:
            score += 1
        review.append({
            "q": question["question_text"],
            "o": [
                question["option_a"],
                question["option_b"],
                question["option_c"],
                question["option_d"],
            ],
            "selectedIndex": selected_index,
            "correctIndex": correct_index,
            "isCorrect": is_correct,
            "explanation": question.get("detailed_explanation") or question.get("explanation") or "",
        })

    return {
        "quiz_id": quiz_id,
        "score": score,
        "total": len(items),
        "review": review,
    }


def _get_or_insert_question(quiz_id: str, item: dict, meta: dict) -> dict:
    question = _build_question(quiz_id, item, meta)

    exact = questions_repo.get_by_hash_any_bot(question.question_hash)
    if exact:
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
            LOG.info("Quiz %s reused similar question %s.", quiz_id, row["id"])
            return row

    return questions_repo.insert_question(question)


def _build_question(quiz_id: str, item: dict, meta: dict) -> Question:
    question_text = _str(item.get("question", item.get("q")))[:TELEGRAM_QUESTION_LIMIT]
    options = [_str(option)[:TELEGRAM_OPTION_LIMIT] for option in item.get("options", item.get("o", []))]
    if len(options) != 4 or not question_text or any(not option for option in options):
        raise ValueError(f"Invalid quiz question in {quiz_id}: expected question text and 4 options.")

    correct_index = int(item.get("correct_index", item.get("a")))
    if not (0 <= correct_index <= 3):
        raise ValueError(f"Invalid correct option in {quiz_id}: {correct_index}")

    explanation = _str(item.get("explanation", item.get("e")))[:TELEGRAM_EXPLANATION_LIMIT]
    detailed = _str(item.get("detailed_explanation", explanation))[:TELEGRAM_DETAILED_EXPLANATION_LIMIT]
    subject = _str(meta.get("subject") or item.get("subject") or "Miscellaneous")
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
        gemini_model=GEMINI_MODEL,
        source=quiz_source(quiz_id),
        week_number=iso_week_number(),
        bot_type=BOT_TYPE,
        question_hash=question_hash(question_text),
        normalized_text=normalized,
    )


def _date_from_quiz_id(quiz_id: str) -> str:
    if len(quiz_id) == 8 and quiz_id.isdigit():
        try:
            return date(int(quiz_id[:4]), int(quiz_id[4:6]), int(quiz_id[6:8])).isoformat()
        except ValueError:
            pass
    return date.today().isoformat()


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()
