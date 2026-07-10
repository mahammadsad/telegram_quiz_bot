"""Generate, persist, post, and recover one subject-scoped quiz at a time."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from config.settings import (
    APP_TIMEZONE,
    MINIAPP_SHORT_NAME,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_CHAT_ID,
    TELEGRAM_FORUM_TOPICS_JSON,
    TELEGRAM_GENERAL_THREAD_ID,
    WRITE_STATIC_QUIZ_JSON,
    require_env,
)
from config.subjects import QUIZ_SUBJECTS, get_subject
from services import chapter_selector, quiz_pack_service
from services.gemini_provider_pool import GeminiGenerationError, GeminiProviderPool
from services.question_validation import QUESTION_COUNT, QuizValidationError, checksum_for_pack, content_checksum, validate_questions
from storage import chapter_history_repo, polls_repo, quiz_runs_repo
from telegram.routing import ForumRouter
from utils.local_time import local_today
from utils.quiz_ids import build_quiz_id

LOG = logging.getLogger("subject_quiz_bot")
ROOT = Path(__file__).resolve().parent
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

MCQ_JSON_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "question": {"type": "STRING"},
            "options": {"type": "ARRAY", "items": {"type": "STRING"}},
            "correct_index": {"type": "INTEGER"},
            "explanation": {"type": "STRING"},
            "detailed_explanation": {"type": "STRING"},
            "difficulty": {"type": "STRING"},
            "subject_key": {"type": "STRING"},
            "chapter": {"type": "STRING"},
        },
        "required": ["question", "options", "correct_index", "explanation", "detailed_explanation", "difficulty", "subject_key", "chapter"],
    },
}


def build_mcq_prompt(subject_key: str, chapter: str) -> str:
    subject = get_subject(subject_key, require_quiz_enabled=True)
    return f"""You are an expert Bengali question setter for Indian and West Bengal competitive exams.
Create exactly 10 MCQs for the single scheduled subject and chapter below.
Canonical subject key: {subject.key}
Internal subject: {subject.internal_subject}
Chapter: {chapter}

Rules:
1. Return one JSON array containing exactly 10 objects and nothing else.
2. Every question must test only this subject and chapter.
3. Bengali question text, a short Bengali explanation, and a detailed Bengali explanation are mandatory.
4. English tests may contain English tested text; Bengali instructions and explanations remain mandatory.
5. Supply exactly four unique non-empty options and correct_index 0..3.
6. Every object must repeat subject_key exactly as {subject.key} and chapter exactly as {chapter}.
7. Use difficulty easy, medium, or hard. Avoid duplicates, truncation, answer-revealing wording, and ambiguity.
8. Questions must suit WBCS, WBPSC, WBP, SSC, Railway, Banking, or TET preparation.
"""


def generate_mcqs(
    subject_key: str,
    chapter: str,
    *,
    pool: GeminiProviderPool | None = None,
) -> tuple[list[dict], dict]:
    pool = pool or GeminiProviderPool()
    prompt = build_mcq_prompt(subject_key, chapter)
    raw_text, generation = pool.generate_subject_quiz(prompt=prompt, response_schema=MCQ_JSON_SCHEMA)
    try:
        raw = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError):
        repair_prompt = (
            prompt
            + "\nThe prior output was malformed JSON. Repair it once. Return only a valid JSON array; "
            + "do not add, remove, or partially return questions."
        )
        repaired_text, generation = pool.generate_subject_quiz(prompt=repair_prompt, response_schema=MCQ_JSON_SCHEMA)
        try:
            raw = json.loads(repaired_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise QuizValidationError("Gemini returned malformed JSON after one repair request.") from exc
    if not isinstance(raw, list):
        raise QuizValidationError("Gemini response must be a JSON array.")
    enriched = []
    for item in raw:
        if isinstance(item, dict):
            enriched.append({"subject_key": subject_key, "chapter": chapter, **item})
        else:
            enriched.append(item)
    return validate_questions(enriched, subject_key, chapter), generation


def valid_saved_pack(quiz_id: str, run: dict | None = None) -> dict | None:
    pack = quiz_pack_service.get_quiz_pack(quiz_id)
    if not pack or len(pack.get("items") or []) != QUESTION_COUNT:
        return None
    meta = pack.get("meta") or {}
    subject_key = meta.get("subject_key") or meta.get("subject")
    chapter = meta.get("chapter") or ""
    raw = []
    for item in pack["items"]:
        question = item.get("question") or {}
        raw.append({
            "question": question.get("question_text"),
            "options": [question.get("option_a"), question.get("option_b"), question.get("option_c"), question.get("option_d")],
            "correct_index": "ABCD".find(str(question.get("correct_option") or "")),
            "explanation": question.get("explanation"),
            "detailed_explanation": question.get("detailed_explanation"),
            "subject_key": subject_key,
            "chapter": chapter,
            "difficulty": question.get("difficulty"),
        })
    try:
        validate_questions(raw, subject_key, chapter)
    except (QuizValidationError, ValueError):
        return None
    checksum = checksum_for_pack(pack)
    if not run or not run.get("content_checksum") or run["content_checksum"] != checksum:
        return None
    return pack


def export_static_quiz_json(pack: dict) -> Path | None:
    """Write only public question data—never answers or explanations."""
    if not WRITE_STATIC_QUIZ_JSON:
        return None
    payload = quiz_pack_service.public_quiz_payload(pack)
    quiz_id = str(pack.get("quiz_id") or (pack.get("meta") or {}).get("quiz_id") or "")
    if not quiz_id or len(payload.get("qs") or []) != QUESTION_COUNT:
        raise QuizValidationError("Refusing to export an incomplete public fallback.")
    path = ROOT / "quizzes" / f"{quiz_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    LOG.info("STATIC_QUIZ_EXPORTED quiz_id=%s answer_key_included=false", quiz_id)
    return path


def forum_router() -> ForumRouter:
    return ForumRouter.from_values(TELEGRAM_FORUM_TOPICS_JSON, TELEGRAM_GENERAL_THREAD_ID)


def validate_runtime_config(*, require_gemini: bool = True) -> ForumRouter:
    require_env("TELEGRAM_BOT_TOKEN")
    require_env("TELEGRAM_CHAT_ID")
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    if require_gemini:
        _require_gemini_provider()
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("Supabase is not configured.")
    if not TELEGRAM_BOT_USERNAME or not MINIAPP_SHORT_NAME:
        raise RuntimeError("TELEGRAM_BOT_USERNAME and MINIAPP_SHORT_NAME are required.")
    return forum_router()


def _require_gemini_provider() -> None:
    if not any(os.environ.get(name) for name in ("GEMINI_API_KEY_PRIMARY", "GEMINI_API_KEY_SECONDARY", "GEMINI_API_KEY")):
        raise RuntimeError("No Gemini provider is configured.")


def run_subject_quiz(
    subject_key: str,
    *,
    target_date: date | None = None,
    force_post: bool = False,
    force_regenerate: bool = False,
    pool: GeminiProviderPool | None = None,
) -> str:
    subject = get_subject(subject_key, require_quiz_enabled=True)
    router = validate_runtime_config(require_gemini=False)
    thread_id = router.for_subject(subject_key)  # validated before spending Gemini quota
    target_date = target_date or local_today()
    quiz_id = build_quiz_id(target_date, subject_key)
    run = quiz_runs_repo.get(quiz_id)
    if run and run.get("status") == "posted" and not force_post and not force_regenerate:
        LOG.info("QUIZ_ALREADY_POSTED subject=%s quiz_id=%s", subject_key, quiz_id)
        return "already_posted"

    pack = None if force_regenerate else valid_saved_pack(quiz_id, run)
    used_saved_pack = pack is not None
    if force_post and not pack:
        raise RuntimeError("--force-post requires an existing valid generated quiz and matching checksum.")

    if pack is None:
        _require_gemini_provider()
        chapter = chapter_selector.select_chapter(subject_key, target_date)
        quiz_runs_repo.upsert({
            "quiz_id": quiz_id,
            "quiz_date": target_date.isoformat(),
            "subject_key": subject_key,
            "subject_display_name": subject.telegram_display_name,
            "internal_subject": subject.internal_subject,
            "chapter": chapter,
            "status": "generating",
            "question_count": 0,
        })
        try:
            questions, generation = generate_mcqs(subject_key, chapter, pool=pool)
            # A prior interrupted save may have left partial delivery rows.
            # Remove only this quiz's delivery set after replacement content
            # has validated, then write all ten rows afresh.
            polls_repo.delete_by_run_slot(quiz_id, "mock_test")
            pack = quiz_pack_service.record_quiz_pack(
                quiz_id,
                questions,
                {
                    "quiz_id": quiz_id,
                    "date": target_date.isoformat(),
                    "subject_key": subject_key,
                    "subject_display_name": subject.telegram_display_name,
                    "chapter": chapter,
                    "generation_model": generation["model"],
                },
                chat_id=_chat_id_as_int(TELEGRAM_CHAT_ID),
            )
            checksum = checksum_for_pack(pack)
            quiz_runs_repo.update_status(
                quiz_id,
                "generating",
                question_count=QUESTION_COUNT,
                generation_provider=generation["provider"],
                generation_model=generation["model"],
                providers_attempted=generation.get("providers_attempted") or [generation["provider"]],
                generation_attempt_count=generation["attempts"],
                retryable=False,
                generated_at=datetime.now(timezone.utc).isoformat(),
                last_error_category=None,
            )
            chapter_history_repo.record(subject_key, chapter, target_date.isoformat(), quiz_id)
            export_static_quiz_json(pack)
            quiz_runs_repo.update_status(quiz_id, "generated", content_checksum=checksum)
            LOG.info(
                "GEMINI_GENERATION_SUCCESS subject=%s quiz_id=%s provider=%s model=%s attempts=%s question_count=10",
                subject_key, quiz_id, generation["provider"], generation["model"], generation["attempts"],
            )
        except Exception as exc:
            category = getattr(exc, "category", "validation_failed" if isinstance(exc, QuizValidationError) else "generation_error")
            safe_attempts = getattr(exc, "attempts", [])
            quiz_runs_repo.update_status(
                quiz_id,
                "generation_failed",
                last_error_category=category,
                last_error_at=datetime.now(timezone.utc).isoformat(),
                providers_attempted=list(dict.fromkeys(row.get("provider") for row in safe_attempts if row.get("provider"))),
                generation_attempt_count=len(safe_attempts),
                retryable=bool(getattr(exc, "retryable", False)),
            )
            send_failure_alert(subject_key, quiz_id, router)
            raise

    chapter = (pack.get("meta") or {}).get("chapter") or (run or {}).get("chapter") or ""
    quiz_runs_repo.update_status(quiz_id, "posting")
    try:
        response = telegram_api("sendMessage", {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_thread_id": thread_id,
            "text": _quiz_post_text(subject.telegram_display_name, chapter),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": "কুইজ শুরু করুন", "url": build_miniapp_url(quiz_id)}]]},
        })
        message = response.get("result") or {}
        quiz_runs_repo.update_status(
            quiz_id,
            "posted",
            posted_at=datetime.now(timezone.utc).isoformat(),
            telegram_chat_id=(message.get("chat") or {}).get("id", _chat_id_as_int(TELEGRAM_CHAT_ID)),
            telegram_thread_id=message.get("message_thread_id", thread_id),
            telegram_message_id=message.get("message_id"),
            last_error_category=None,
        )
        try:
            quiz_pack_service.mark_pack_posted(pack)
        except Exception:
            # Delivery is already confirmed and persisted. Question-usage
            # metadata is secondary and must never turn this into a repost.
            LOG.warning("QUESTION_USAGE_UPDATE_FAILED subject=%s quiz_id=%s", subject_key, quiz_id)
        LOG.info("TELEGRAM_QUIZ_POSTED subject=%s quiz_id=%s thread_id_configured=true message_id=%s", subject_key, quiz_id, message.get("message_id"))
        return "posted_from_saved_quiz" if used_saved_pack else "generated_and_posted"
    except Exception:
        quiz_runs_repo.update_status(
            quiz_id,
            "posting_failed",
            last_error_category="telegram_posting_failed",
            last_error_at=datetime.now(timezone.utc).isoformat(),
        )
        raise


def recover_missed_quizzes(*, now: datetime | None = None, pool: GeminiProviderPool | None = None) -> tuple[dict[str, str], bool]:
    current = now or datetime.now(ZoneInfo(APP_TIMEZONE))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(APP_TIMEZONE))
    today = current.astimezone(ZoneInfo(APP_TIMEZONE)).date()
    current_hhmm = current.astimezone(ZoneInfo(APP_TIMEZONE)).strftime("%H:%M")
    summary: dict[str, str] = {}
    unresolved = False
    for subject in QUIZ_SUBJECTS:
        if subject.scheduled_time_ist > current_hhmm:
            summary[subject.key] = "not_due"
            continue
        quiz_id = build_quiz_id(today, subject.key)
        run = quiz_runs_repo.get(quiz_id)
        if run and run.get("status") == "posted":
            summary[subject.key] = "already_posted"
            continue
        had_saved = bool(valid_saved_pack(quiz_id, run))
        try:
            result = run_subject_quiz(subject.key, target_date=today, pool=pool)
            summary[subject.key] = "posted_from_saved_quiz" if had_saved else "recovered_and_posted"
        except Exception as exc:
            summary[subject.key] = "generation_failed_retryable" if getattr(exc, "retryable", True) else "failed_non_retryable"
            unresolved = unresolved or getattr(exc, "retryable", True)
    LOG.info("RECOVERY_SUMMARY %s", " ".join(f"{key}={value}" for key, value in summary.items()))
    return summary, unresolved


def telegram_api(method: str, payload: dict) -> dict:
    token = require_env("TELEGRAM_BOT_TOKEN")
    try:
        response = requests.post(TELEGRAM_API_BASE.format(token=token, method=method), json=payload, timeout=30)
    except requests.RequestException:
        raise RuntimeError(f"Telegram {method} network request failed.") from None
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram {method} failed with status {response.status_code}.") from exc
    if not response.ok or not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed with status {response.status_code}.")
    return result


def send_failure_alert(subject_key: str, quiz_id: str, router: ForumRouter | None = None) -> None:
    subject = get_subject(subject_key, require_quiz_enabled=True)
    text = (
        "⚠️ Mock Test তৈরি করা যায়নি\n\n"
        f"বিষয়: {subject.telegram_display_name}\nQuiz ID: {quiz_id}\n\n"
        "Primary ও Secondary Gemini provider সাময়িকভাবে ব্যর্থ হয়েছে।\n"
        "অসম্পূর্ণ Quiz পোস্ট করা হয়নি।\nRecovery process পরে আবার চেষ্টা করবে।"
    )
    payload: dict = {"chat_id": TELEGRAM_ADMIN_CHAT_ID or TELEGRAM_CHAT_ID, "text": text}
    if not TELEGRAM_ADMIN_CHAT_ID and router and router.general_thread_id:
        payload["message_thread_id"] = router.general_thread_id
    try:
        telegram_api("sendMessage", payload)
    except Exception:
        LOG.warning("ADMIN_ALERT_FAILED subject=%s quiz_id=%s", subject_key, quiz_id)


def send_schedule_announcement() -> None:
    router = validate_runtime_config(require_gemini=False)
    lines = ["📌 <b>দৈনিক Mock Test সূচি</b>", ""]
    for subject in QUIZ_SUBJECTS:
        lines.append(f"{subject.scheduled_time_ist} IST · {html.escape(subject.telegram_display_name)}")
    payload: dict = {"chat_id": TELEGRAM_CHAT_ID, "text": "\n".join(lines), "parse_mode": "HTML"}
    if router.general_thread_id:
        payload["message_thread_id"] = router.general_thread_id
    telegram_api("sendMessage", payload)


def preflight() -> dict[str, bool]:
    topics_ok = False
    try:
        forum_router()
        topics_ok = True
    except Exception:
        pass
    values = {
        "primary_key_configured": bool(os.environ.get("GEMINI_API_KEY_PRIMARY") or os.environ.get("GEMINI_API_KEY")),
        "secondary_key_configured": bool(os.environ.get("GEMINI_API_KEY_SECONDARY")),
        "failover_enabled": os.environ.get("GEMINI_FAILOVER_ENABLED", "true").lower() == "true",
        "telegram_topics_configured": topics_ok,
        "supabase_configured": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")),
    }
    for key, value in values.items():
        print(f"{key}={str(value).lower()}")
    return values


def build_miniapp_url(quiz_id: str) -> str:
    return f"https://t.me/{TELEGRAM_BOT_USERNAME}/{MINIAPP_SHORT_NAME}?startapp={quiz_id}"


def _quiz_post_text(display_name: str, chapter: str) -> str:
    return (
        "📝 <b>আজকের মক টেস্ট প্রস্তুত</b>\n\n"
        f"📚 <b>বিষয়:</b> {html.escape(display_name)}\n"
        f"📖 <b>চ্যাপ্টার:</b> {html.escape(chapter)}\n"
        "🔢 <b>প্রশ্ন:</b> ১০টি\n\nসাবমিটের পর স্কোর, ব্যাখ্যা ও এই কুইজের leaderboard দেখুন।"
    )


def _chat_id_as_int(chat_id: str) -> int:
    try:
        return int(chat_id)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Subject-scoped Telegram quiz bot")
    parser.add_argument("--mode", required=True, choices=["subject-quiz", "recover-missed-quizzes", "announce", "preflight"])
    parser.add_argument("--subject")
    parser.add_argument("--force-post", action="store_true")
    parser.add_argument("--force-regenerate", action="store_true")
    args = parser.parse_args()
    if args.force_post and args.force_regenerate:
        parser.error("--force-post and --force-regenerate are mutually exclusive.")
    if args.mode != "subject-quiz" and (args.force_post or args.force_regenerate):
        parser.error("Force flags apply only to subject-quiz mode.")
    try:
        if args.mode == "subject-quiz":
            if not args.subject:
                parser.error("--subject is required for subject-quiz mode.")
            run_subject_quiz(args.subject, force_post=args.force_post, force_regenerate=args.force_regenerate)
        elif args.mode == "recover-missed-quizzes":
            _, unresolved = recover_missed_quizzes()
            if unresolved:
                raise RuntimeError("Recovery finished with unresolved retryable failures.")
        elif args.mode == "announce":
            send_schedule_announcement()
        else:
            values = preflight()
            telegram_runtime_configured = all(
                os.environ.get(name)
                for name in (
                    "TELEGRAM_BOT_TOKEN",
                    "TELEGRAM_CHAT_ID",
                    "TELEGRAM_BOT_USERNAME",
                    "MINIAPP_SHORT_NAME",
                )
            )
            if (
                not values["primary_key_configured"]
                or not values["telegram_topics_configured"]
                or not values["supabase_configured"]
                or not telegram_runtime_configured
            ):
                raise RuntimeError("Configuration preflight failed.")
    except Exception as exc:
        LOG.error("RUN_FAILED category=%s", getattr(exc, "category", type(exc).__name__))
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
