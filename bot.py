"""
WB Exam Quiz Pack Bot
=====================
Generates Bengali mock-test quiz packs, stores them in the same Supabase
Postgres schema used by repo_1, then posts a Telegram Mini App direct link.

Required environment variables:
  GEMINI_API_KEY
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  TELEGRAM_BOT_USERNAME
  MINIAPP_SHORT_NAME
  SUPABASE_URL
  SUPABASE_SERVICE_KEY
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import random
import sys
import time
from datetime import date, datetime, timedelta

import requests
from google import genai
from google.genai import types

from config.settings import (
    GEMINI_MODEL,
    MINIAPP_SHORT_NAME,
    QUESTIONS_PER_RUN,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    SYLLABUS_STATE_KEY,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_CHAT_ID,
    require_env,
)
from services import quiz_pack_service
from storage import bot_state_repo

MAX_RETRIES = 4
RETRY_BASE_DELAY = 3
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

DEFAULT_EXAM_FOCUS = "WBCS প্রিলিমিনারি ও WBPSC গ্রুপ-ডি"
SUBJECTS_MON_TO_FRI = ["ইতিহাস", "ভূগোল", "সাধারণ বিজ্ঞান", "গণিত", "রাজনীতি বিজ্ঞান"]
CURRENT_AFFAIRS_SUBJECT = "কারেন্ট অ্যাফেয়ার্স"
CURRENT_AFFAIRS_CHAPTER = "সাম্প্রতিক জাতীয় ও আন্তর্জাতিক ঘটনা"

BN_WEEKDAY_NAMES = {
    0: "সোমবার", 1: "মঙ্গলবার", 2: "বুধবার",
    3: "বৃহস্পতিবার", 4: "শুক্রবার", 5: "শনিবার",
}
BN_MONTHS = [
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
    "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
]
_BN_DIGIT_MAP = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wb_quiz_pack_bot")


def bn_num(n: int) -> str:
    return str(n).translate(_BN_DIGIT_MAP)


def format_week_label_bn(monday: date) -> str:
    saturday = monday + timedelta(days=5)
    if monday.year == saturday.year and monday.month == saturday.month:
        return f"{bn_num(monday.day)} – {bn_num(saturday.day)} {BN_MONTHS[monday.month - 1]}, {bn_num(monday.year)}"
    if monday.year == saturday.year:
        return (
            f"{bn_num(monday.day)} {BN_MONTHS[monday.month - 1]} – "
            f"{bn_num(saturday.day)} {BN_MONTHS[saturday.month - 1]}, {bn_num(monday.year)}"
        )
    return (
        f"{bn_num(monday.day)} {BN_MONTHS[monday.month - 1]}, {bn_num(monday.year)} – "
        f"{bn_num(saturday.day)} {BN_MONTHS[saturday.month - 1]}, {bn_num(saturday.year)}"
    )


def load_state() -> dict:
    raw = bot_state_repo.get_value(SYLLABUS_STATE_KEY)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Invalid JSON in bot_state[%s]; starting fresh.", SYLLABUS_STATE_KEY)
    return {"exam_focus": DEFAULT_EXAM_FOCUS, "history": {}}


def save_state(state: dict) -> None:
    bot_state_repo.set_value(SYLLABUS_STATE_KEY, json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    log.info("Saved syllabus state in Supabase bot_state[%s].", SYLLABUS_STATE_KEY)


WEEKLY_CHAPTERS_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "subject": {"type": "STRING"},
            "chapter": {"type": "STRING"},
        },
        "required": ["subject", "chapter"],
    },
}


def _build_syllabus_prompt(exam_focus: str, history: dict) -> str:
    blocks = []
    for subject in SUBJECTS_MON_TO_FRI:
        covered = history.get(subject, [])[-20:]
        covered_text = "; ".join(covered) if covered else "(এখনও কিছু কভার করা হয়নি)"
        blocks.append(f'- বিষয়: "{subject}" | ইতিমধ্যে পড়ানো চ্যাপ্টার: {covered_text}')

    return f"""তুমি একজন অভিজ্ঞ প্রশ্নপত্র/সিলেবাস পরিকল্পনাকারী।
লক্ষ্য পরীক্ষা: {exam_focus}

নিচের বিষয়গুলির প্রতিটির জন্য আগামী সপ্তাহে পড়ানোর মতো ঠিক ১টি করে নতুন
চ্যাপ্টার/টপিক বেছে নাও। আগের চ্যাপ্টার পুনরাবৃত্তি করা যাবে না।

{chr(10).join(blocks)}

আউটপুট অবশ্যই ঠিক {len(SUBJECTS_MON_TO_FRI)}টি অবজেক্টসহ JSON array হবে, এই ক্রমে:
{", ".join(SUBJECTS_MON_TO_FRI)}
প্রতিটি অবজেক্টে থাকবে "subject" এবং "chapter"। শুধুমাত্র JSON ফেরত দাও।
"""


def generate_weekly_chapters(exam_focus: str, history: dict) -> list[str]:
    client = genai.Client(api_key=require_env("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_build_syllabus_prompt(exam_focus, history),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WEEKLY_CHAPTERS_SCHEMA,
            temperature=0.8,
        ),
    )
    raw = json.loads(response.text)
    chapters = [str(item.get("chapter", "")).strip() for item in raw if str(item.get("chapter", "")).strip()]
    if len(chapters) != len(SUBJECTS_MON_TO_FRI):
        raise ValueError(f"Expected {len(SUBJECTS_MON_TO_FRI)} chapters from Gemini, got {len(chapters)}.")
    return chapters


def ensure_current_week(state: dict) -> tuple[dict, bool]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if state.get("week_start_date") == monday.isoformat() and state.get("days"):
        return state, False

    exam_focus = state.get("exam_focus") or DEFAULT_EXAM_FOCUS
    history = state.get("history") or {}
    chapters = retry_with_backoff(
        generate_weekly_chapters,
        exam_focus,
        history,
        what="Gemini weekly syllabus generation",
    )

    days = {}
    for i, subject in enumerate(SUBJECTS_MON_TO_FRI):
        chapter = chapters[i]
        days[str(i)] = {"day_bn": BN_WEEKDAY_NAMES[i], "subject": subject, "chapter": chapter}
        history.setdefault(subject, []).append(chapter)
        history[subject] = history[subject][-20:]
    days["5"] = {
        "day_bn": BN_WEEKDAY_NAMES[5],
        "subject": CURRENT_AFFAIRS_SUBJECT,
        "chapter": CURRENT_AFFAIRS_CHAPTER,
    }

    state.update({
        "exam_focus": exam_focus,
        "history": history,
        "week_start_date": monday.isoformat(),
        "week_label_bn": format_week_label_bn(monday),
        "days": days,
    })
    save_state(state)
    return state, True


def retry_with_backoff(fn, *args, retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY, what="operation", **kwargs):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            wait = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
            log.warning("%s failed (attempt %d/%d): %s", what, attempt, retries, exc)
            if attempt < retries:
                time.sleep(wait)
    raise last_err


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
        },
        "required": ["question", "options", "correct_index", "explanation", "detailed_explanation"],
    },
}


def _build_mcq_prompt(subject: str, chapter: str, exam_focus: str, num_questions: int) -> str:
    return f"""You are an expert Bengali MCQ question setter for West Bengal government exams.
Target difficulty: {exam_focus}

Create exactly {num_questions} MCQs for:
Subject: {subject}
Chapter/topic: {chapter}

Rules:
1. Bengali language only, except standard abbreviations/proper nouns.
2. Exactly 4 plausible options per question.
3. correct_index is 0, 1, 2, or 3.
4. Questions must match WBCS/WBPSC/WB Police/SSC/Railway exam style.
5. explanation: one short Bengali sentence.
6. detailed_explanation: 2-4 useful Bengali sentences for result review.
7. Return only the JSON array described by the schema.
"""


def generate_mcqs(subject: str, chapter: str, exam_focus: str, num_questions: int = QUESTIONS_PER_RUN) -> list[dict]:
    client = genai.Client(api_key=require_env("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_build_mcq_prompt(subject, chapter, exam_focus, num_questions),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MCQ_JSON_SCHEMA,
            temperature=0.9,
        ),
    )
    raw = json.loads(response.text)
    clean = []
    for item in raw:
        try:
            question = str(item["question"]).strip()
            options = [str(option).strip() for option in item["options"]]
            correct_index = int(item["correct_index"])
            explanation = str(item.get("explanation", "")).strip()
            detailed = str(item.get("detailed_explanation", explanation)).strip()
            if question and len(options) == 4 and 0 <= correct_index <= 3:
                clean.append({
                    "question": question,
                    "options": options,
                    "correct_index": correct_index,
                    "explanation": explanation,
                    "detailed_explanation": detailed,
                })
        except (KeyError, TypeError, ValueError):
            continue
    if len(clean) < 5:
        raise ValueError(f"Gemini returned only {len(clean)} usable questions.")
    return clean


def quiz_id_for_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def validate_runtime_config() -> None:
    require_env("GEMINI_API_KEY")
    require_env("TELEGRAM_BOT_TOKEN")
    require_env("TELEGRAM_CHAT_ID")
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required.")
    if not TELEGRAM_BOT_USERNAME or not MINIAPP_SHORT_NAME:
        raise RuntimeError("TELEGRAM_BOT_USERNAME and MINIAPP_SHORT_NAME are required for Mini App links.")


def build_miniapp_url(quiz_id: str) -> str:
    return f"https://t.me/{TELEGRAM_BOT_USERNAME}/{MINIAPP_SHORT_NAME}?startapp={quiz_id}"


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def telegram_api(method: str, payload: dict) -> dict:
    token = require_env("TELEGRAM_BOT_TOKEN")
    url = TELEGRAM_API_BASE.format(token=token, method=method)
    resp = requests.post(url, json=payload, timeout=30)
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {result}")
    return result


def send_sunday_announcement() -> None:
    validate_runtime_config()
    state, _ = ensure_current_week(load_state())
    lines = [
        "📌 <b>এই সপ্তাহের মক টেস্ট প্ল্যান</b>",
        f"🎯 <b>লক্ষ্য পরীক্ষা:</b> {esc(state['exam_focus'])}",
        f"🗓️ <b>{esc(state['week_label_bn'])}</b>",
        "",
    ]
    for i in range(6):
        d = state["days"][str(i)]
        lines.append(f"<b>{esc(d['day_bn'])}</b> · {esc(d['subject'])} — {esc(d['chapter'])}")
    lines.extend(["", "প্রতিদিনের কুইজ Mini App-এ খুলবে, স্কোর সরাসরি ড্যাশবোর্ডে জমা হবে।"])
    retry_with_backoff(
        telegram_api,
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "\n".join(lines),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        what="Sunday announcement",
    )
    log.info("Sunday syllabus announcement sent.")


def send_daily_quiz() -> None:
    validate_runtime_config()
    today_idx = datetime.now().weekday()
    if today_idx == 6:
        log.info("Today is Sunday; quiz generation skipped.")
        return

    quiz_id = quiz_id_for_date(date.today())
    pack = quiz_pack_service.get_quiz_pack(quiz_id)

    if not pack:
        state, _ = ensure_current_week(load_state())
        day_info = state["days"][str(today_idx)]
        subject, chapter = day_info["subject"], day_info["chapter"]
        log.info("Generating %d MCQs for %s / %s.", QUESTIONS_PER_RUN, subject, chapter)
        questions = retry_with_backoff(
            generate_mcqs,
            subject,
            chapter,
            state["exam_focus"],
            QUESTIONS_PER_RUN,
            what="Gemini MCQ generation",
        )
        meta = {
            "subject": subject,
            "chapter": chapter,
            "date": date.today().isoformat(),
            "quiz_id": quiz_id,
        }
        pack = quiz_pack_service.record_quiz_pack(
            quiz_id,
            questions,
            meta,
            chat_id=_chat_id_as_int(TELEGRAM_CHAT_ID),
        )

    meta = pack["meta"]
    quiz_url = build_miniapp_url(quiz_id)
    text = (
        "📝 <b>আজকের মক টেস্ট প্রস্তুত</b>\n\n"
        f"📚 <b>বিষয়:</b> {esc(meta.get('subject', ''))}\n"
        f"📖 <b>চ্যাপ্টার:</b> {esc(meta.get('chapter', ''))}\n"
        f"🔢 <b>প্রশ্ন:</b> {len(pack['items'])}টি\n\n"
        "স্কোর ও উত্তরপত্র সাবমিটের পর ড্যাশবোর্ডে আপডেট হবে।"
    )
    keyboard = {"inline_keyboard": [[{"text": "কুইজ শুরু করুন", "url": quiz_url}]]}
    retry_with_backoff(
        telegram_api,
        "sendMessage",
        {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "reply_markup": keyboard},
        what="Daily quiz post",
    )
    quiz_pack_service.mark_pack_posted(pack)
    log.info("Daily quiz %s posted and marked used.", quiz_id)


def _chat_id_as_int(chat_id: str) -> int:
    try:
        return int(chat_id)
    except (TypeError, ValueError):
        return 0


def _safe_run(fn) -> None:
    try:
        fn()
    except Exception:
        log.exception("Unhandled error while running %s", fn.__name__)


def run_scheduler_daemon() -> None:
    import schedule

    schedule.every().sunday.at("20:00").do(_safe_run, send_sunday_announcement)
    for day_scheduler in (
        schedule.every().monday,
        schedule.every().tuesday,
        schedule.every().wednesday,
        schedule.every().thursday,
        schedule.every().friday,
        schedule.every().saturday,
    ):
        day_scheduler.at("18:30").do(_safe_run, send_daily_quiz)

    log.info("Scheduler daemon started. Use TZ=Asia/Kolkata if the host is not already on IST.")
    while True:
        schedule.run_pending()
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="WB Govt Exam Telegram Quiz Pack Bot")
    parser.add_argument("--mode", choices=["announce", "quiz", "daemon"], required=True)
    args = parser.parse_args()
    try:
        if args.mode == "announce":
            send_sunday_announcement()
        elif args.mode == "quiz":
            send_daily_quiz()
        else:
            run_scheduler_daemon()
    except Exception:
        log.exception("Fatal error.")
        sys.exit(1)


if __name__ == "__main__":
    main()
