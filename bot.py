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
import os
import random
import re
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

DEFAULT_EXAM_FOCUS = (
    "WBCS, WBPSC Clerkship/Miscellaneous, WB Police, Kolkata Police, SSC, Railway, "
    "Banking, Primary TET/School Service এবং অন্যান্য ভারতীয় competitive exams"
)

# Gemini uses this broad map as the syllabus universe. It is deliberately
# written as an exam-oriented topic map instead of a narrow weekly routine.
COMPETITIVE_EXAM_TOPIC_SCOPE = {
    "History": [
        "প্রাচীন ভারত", "মধ্যযুগীয় ভারত", "আধুনিক ভারত", "বাংলার ইতিহাস",
        "জাতীয় আন্দোলন", "গভর্নর জেনারেল ও ভাইসরয়", "সামাজিক-ধর্মীয় সংস্কার আন্দোলন",
        "সংবিধান গঠনের পটভূমি",
    ],
    "Geography": [
        "ভারতের ভৌগোলিক অবস্থান", "পশ্চিমবঙ্গের ভূগোল", "নদী ও জলসম্পদ",
        "জলবায়ু", "মাটি", "কৃষি", "খনিজ ও শিল্প", "জনসংখ্যা",
        "বিশ্ব ভূগোলের মৌলিক ধারণা",
    ],
    "Polity": [
        "ভারতীয় সংবিধানের বৈশিষ্ট্য", "মৌলিক অধিকার ও কর্তব্য",
        "রাষ্ট্র পরিচালনার নির্দেশমূলক নীতি", "রাষ্ট্রপতি", "প্রধানমন্ত্রী ও মন্ত্রিসভা",
        "সংসদ", "সুপ্রিম কোর্ট ও হাইকোর্ট", "নির্বাচন কমিশন",
        "পঞ্চায়েত ও পৌরসভা", "সাংবিধানিক সংস্থা",
    ],
    "Economics": [
        "ভারতীয় অর্থনীতির মৌলিক ধারণা", "পরিকল্পনা ও নীতি আয়োগ",
        "জাতীয় আয়", "ব্যাংকিং", "RBI", "মুদ্রাস্ফীতি", "বাজেট",
        "করব্যবস্থা", "দারিদ্র্য ও বেকারত্ব", "সরকারি প্রকল্প",
    ],
    "General Science": [
        "পদার্থবিদ্যা", "রসায়ন", "জীববিদ্যা", "মানবদেহ",
        "রোগ ও পুষ্টি", "পরিবেশ বিজ্ঞান", "দৈনন্দিন জীবনে বিজ্ঞান",
        "পরিমাপের একক ও যন্ত্র", "মহাকাশ ও প্রযুক্তি",
    ],
    "Mathematics": [
        "সংখ্যা পদ্ধতি", "শতকরা", "লাভ-ক্ষতি", "সরল ও চক্রবৃদ্ধি সুদ",
        "অনুপাত-সমানুপাত", "সময় ও কাজ", "সময়-দূরত্ব", "গড়",
        "মিশ্রণ", "সরলীকরণ", "ডেটা ইন্টারপ্রিটেশন",
    ],
    "Reasoning": [
        "সিরিজ", "অ্যানালজি", "কোডিং-ডিকোডিং", "রক্তের সম্পর্ক",
        "দিক নির্ণয়", "সিলজিজম", "ভেন ডায়াগ্রাম", "বসার বিন্যাস",
        "নন-ভার্বাল রিজনিং",
    ],
    "English": [
        "synonym-antonym", "one word substitution", "idioms and phrases",
        "preposition", "article", "voice", "narration", "tense",
        "subject-verb agreement", "error spotting",
    ],
    "Bengali": [
        "ব্যাকরণ", "সমার্থক-বিপরীতার্থক শব্দ", "বাগধারা", "কারক-বিভক্তি",
        "সমাস", "সন্ধি", "শুদ্ধ বানান", "বাক্য সংশোধন", "বাংলা সাহিত্য",
    ],
    "Computer": [
        "কম্পিউটারের মৌলিক ধারণা", "হার্ডওয়্যার-সফটওয়্যার", "ইন্টারনেট",
        "MS Office", "সাইবার নিরাপত্তা", "ডেটাবেস", "অপারেটিং সিস্টেম",
    ],
    "Current Affairs": [
        "জাতীয় ঘটনা", "আন্তর্জাতিক ঘটনা", "পশ্চিমবঙ্গ", "পুরস্কার",
        "খেলাধুলা", "বিজ্ঞান ও প্রযুক্তি", "নিয়োগ ও সরকারি প্রকল্প",
    ],
}
WEEKLY_TOPIC_COUNT = 6
TOPIC_PLANNER_VERSION = 4
TOPIC_REPEAT_COOLDOWN_DAYS = 21
TOPIC_SPACED_REVIEW_DAYS = (3, 7, 14, 30)
TOPIC_EVENT_LIMIT = 300
POSTED_QUIZ_STATE_PREFIX = "mock_test_posted_quiz"

BN_WEEKDAY_NAMES = {
    0: "সোমবার", 1: "মঙ্গলবার", 2: "বুধবার",
    3: "বৃহস্পতিবার", 4: "শুক্রবার", 5: "শনিবার",
}
BN_MONTHS = [
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
    "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
]
_BN_DIGIT_MAP = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_TOPIC_PUNCT_RE = re.compile(r"[।,.!?\"'‘’“”:;()\[\]{}—–\-_/|]+")
_WHITESPACE_RE = re.compile(r"\s+")

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


def topic_key(subject: str, chapter: str) -> str:
    text = f"{subject} {chapter}".strip().lower()
    text = _TOPIC_PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def topic_events_from_state(state: dict) -> list[dict]:
    events = []
    seen = set()
    keys_with_dated_events = set()
    for raw in state.get("topic_events") or []:
        if not isinstance(raw, dict):
            continue
        subject = str(raw.get("subject", "")).strip()
        chapter = str(raw.get("chapter", "")).strip()
        if not subject or not chapter:
            continue
        key = str(raw.get("key") or topic_key(subject, chapter))
        event = {
            "subject": subject,
            "chapter": chapter,
            "key": key,
            "planned_for": raw.get("planned_for"),
            "planned_at": raw.get("planned_at"),
        }
        marker = (key, event.get("planned_for"), event.get("planned_at"))
        if marker not in seen:
            events.append(event)
            seen.add(marker)
            keys_with_dated_events.add(key)

    # Backfill older state shape. Those entries may not have dates, but they
    # still help block exact repeats after upgrading from the older planner.
    for subject, chapters in (state.get("history") or {}).items():
        if not isinstance(chapters, list):
            continue
        for chapter in chapters:
            chapter_text = str(chapter).strip()
            if not chapter_text:
                continue
            key = topic_key(str(subject), chapter_text)
            if key in keys_with_dated_events:
                continue
            marker = (key, None, None)
            if marker in seen:
                continue
            events.append({
                "subject": str(subject),
                "chapter": chapter_text,
                "key": key,
                "planned_for": None,
                "planned_at": None,
            })
            seen.add(marker)
    return events[-TOPIC_EVENT_LIMIT:]


def event_topic_date(event: dict) -> date | None:
    return parse_iso_date(event.get("planned_for")) or parse_iso_date(event.get("planned_at"))


def is_review_due(event_date: date, planned_for: date) -> bool:
    return (planned_for - event_date).days in TOPIC_SPACED_REVIEW_DAYS


def is_topic_allowed(key: str, events: list[dict], planned_for: date, selected_keys: set[str]) -> bool:
    if key in selected_keys:
        return False
    for event in events:
        if event.get("key") != key:
            continue
        event_date = event_topic_date(event)
        if event_date is None:
            return False
        age_days = (planned_for - event_date).days
        if age_days < 0:
            return False
        if age_days < TOPIC_REPEAT_COOLDOWN_DAYS and not is_review_due(event_date, planned_for):
            return False
    return True


def topic_memory_blocks(state: dict, monday: date) -> tuple[str, str]:
    events = topic_events_from_state(state)
    saturday = monday + timedelta(days=5)
    recent_lines = []
    review_lines = []

    for event in reversed(events[-80:]):
        event_date = event_topic_date(event)
        label = f"{event['subject']} — {event['chapter']}"
        if event_date is None:
            recent_lines.append(f"- {label}")
            continue

        due_this_week = False
        for offset in TOPIC_SPACED_REVIEW_DAYS:
            due_date = event_date + timedelta(days=offset)
            if monday <= due_date <= saturday:
                review_lines.append(f"- {due_date.isoformat()}: {label}")
                due_this_week = True
                break

        age_days = (monday - event_date).days
        if 0 <= age_days < TOPIC_REPEAT_COOLDOWN_DAYS and not due_this_week:
            recent_lines.append(f"- {event_date.isoformat()}: {label}")

    recent_text = "\n".join(recent_lines[:60]) or "(কোনো recent topic নেই)"
    review_text = "\n".join(review_lines[:20]) or "(এই সপ্তাহে নির্দিষ্ট revision topic নেই)"
    return recent_text, review_text


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


WEEKLY_TOPICS_SCHEMA = {
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


def _build_syllabus_prompt(exam_focus: str, state: dict, monday: date) -> str:
    scope_lines = []
    for subject, topics in COMPETITIVE_EXAM_TOPIC_SCOPE.items():
        scope_lines.append(f"- {subject}: {', '.join(topics)}")

    recent_text, review_text = topic_memory_blocks(state, monday)

    return f"""তুমি একজন অভিজ্ঞ প্রশ্নপত্র/সিলেবাস পরিকল্পনাকারী।
লক্ষ্য পরীক্ষা: {exam_focus}

এই bot-এর কাজ হলো competitive exam-এ আসতে পারে এমন সব গুরুত্বপূর্ণ বিষয়ে
বাংলা MCQ practice করানো। নিচের syllabus universe থেকে আগামী ৬ দিনের জন্য
ঠিক {WEEKLY_TOPIC_COUNT}টি fresh quiz topic বেছে নাও।

=== Syllabus universe ===
{chr(10).join(scope_lines)}

=== Blocked recent topics: এগুলো repeat করবে না ===
{recent_text}

=== Spaced-repetition review topics: চাইলে এগুলো revision হিসেবে নেওয়া যাবে ===
{review_text}

নিয়ম:
1. Blocked recent topics থেকে কোনো topic repeat করবে না।
2. Spaced-repetition list থেকে topic নিলে সেটি revision হিসেবে নেওয়া যাবে,
   কিন্তু একই wording নয়; একটু ভিন্ন angle/subtopic করবে।
3. সপ্তাহে subject mix balanced রাখবে: static GK, math/reasoning, language,
   science/current affairs — সব দিক ঘুরে আসবে।
4. chapter খুব নির্দিষ্ট হবে, যেমন "মৌলিক অধিকার: Article 14-18" বা
   "সময় ও কাজ: pipe and cistern"। অস্পষ্ট "History" টাইপ topic নয়।
5. প্রশ্ন WBCS/WBPSC/WB Police/SSC/Railway/Banking/TET ধরনের পরীক্ষার উপযোগী হবে।
6. আউটপুট অবশ্যই ঠিক {WEEKLY_TOPIC_COUNT}টি object সহ JSON array হবে।
7. প্রতিটি object-এ থাকবে "subject" এবং "chapter"। subject ইংরেজি category
   name হতে পারে, chapter বাংলা হবে। শুধুমাত্র JSON ফেরত দাও।
"""


def generate_weekly_topics(exam_focus: str, state: dict, monday: date) -> list[dict]:
    client = genai.Client(api_key=require_env("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_build_syllabus_prompt(exam_focus, state, monday),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WEEKLY_TOPICS_SCHEMA,
            temperature=0.8,
        ),
    )
    raw = json.loads(response.text)
    topics = []
    for item in raw:
        subject = str(item.get("subject", "")).strip()
        chapter = str(item.get("chapter", "")).strip()
        if subject and chapter:
            topics.append({"subject": subject, "chapter": chapter})
    if len(topics) != WEEKLY_TOPIC_COUNT:
        raise ValueError(f"Expected {WEEKLY_TOPIC_COUNT} topics from Gemini, got {len(topics)}.")
    return topics


def validate_weekly_topics(raw_topics: list[dict], state: dict, monday: date) -> list[dict]:
    events = topic_events_from_state(state)
    selected_keys: set[str] = set()
    accepted: list[dict] = []

    for raw in raw_topics:
        if len(accepted) >= WEEKLY_TOPIC_COUNT:
            break
        subject = str(raw.get("subject", "")).strip()
        chapter = str(raw.get("chapter", "")).strip()
        if not subject or not chapter:
            continue
        planned_for = monday + timedelta(days=len(accepted))
        key = topic_key(subject, chapter)
        if not is_topic_allowed(key, events, planned_for, selected_keys):
            log.info("Rejected repeated topic from planner: %s / %s", subject, chapter)
            continue
        accepted.append({"subject": subject, "chapter": chapter, "key": key})
        selected_keys.add(key)

    return accepted


def fill_missing_weekly_topics(topics: list[dict], state: dict, monday: date) -> list[dict]:
    events = topic_events_from_state(state)
    selected_keys = {topic["key"] for topic in topics}
    candidates = [
        {"subject": subject, "chapter": chapter, "key": topic_key(subject, chapter)}
        for subject, chapters in COMPETITIVE_EXAM_TOPIC_SCOPE.items()
        for chapter in chapters
    ]
    random.shuffle(candidates)

    for candidate in candidates:
        if len(topics) >= WEEKLY_TOPIC_COUNT:
            break
        planned_for = monday + timedelta(days=len(topics))
        if not is_topic_allowed(candidate["key"], events, planned_for, selected_keys):
            continue
        topics.append(candidate)
        selected_keys.add(candidate["key"])

    if len(topics) < WEEKLY_TOPIC_COUNT:
        raise ValueError("Could not build enough non-repeating weekly topics.")
    return topics


def plan_weekly_topics(exam_focus: str, state: dict, monday: date) -> list[dict]:
    best: list[dict] = []
    for attempt in range(1, 4):
        raw_topics = generate_weekly_topics(exam_focus, state, monday)
        topics = validate_weekly_topics(raw_topics, state, monday)
        if len(topics) > len(best):
            best = topics
        if len(topics) == WEEKLY_TOPIC_COUNT:
            return topics
        log.warning(
            "Topic planner returned %d/%d usable non-repeating topics on attempt %d.",
            len(topics),
            WEEKLY_TOPIC_COUNT,
            attempt,
        )
    return fill_missing_weekly_topics(best, state, monday)


def remember_planned_topics(state: dict, topics: list[dict], monday: date) -> dict:
    history = state.get("history") or {}
    events = topic_events_from_state(state)
    existing_markers = {
        (event.get("key"), event.get("planned_for"))
        for event in events
    }
    planned_at = date.today().isoformat()

    for i, topic in enumerate(topics):
        subject = topic["subject"]
        chapter = topic["chapter"]
        planned_for = (monday + timedelta(days=i)).isoformat()
        key = topic.get("key") or topic_key(subject, chapter)
        history.setdefault(subject, []).append(chapter)
        history[subject] = history[subject][-50:]
        marker = (key, planned_for)
        if marker not in existing_markers:
            events.append({
                "subject": subject,
                "chapter": chapter,
                "key": key,
                "planned_for": planned_for,
                "planned_at": planned_at,
            })
            existing_markers.add(marker)

    state["history"] = history
    state["topic_events"] = events[-TOPIC_EVENT_LIMIT:]
    return state


def ensure_current_week(state: dict) -> tuple[dict, bool]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if (
        state.get("week_start_date") == monday.isoformat()
        and state.get("days")
        and state.get("planner_version") == TOPIC_PLANNER_VERSION
    ):
        return state, False

    exam_focus = state.get("exam_focus") or DEFAULT_EXAM_FOCUS
    topics = retry_with_backoff(
        plan_weekly_topics,
        exam_focus,
        state,
        monday,
        what="Gemini weekly competitive-topic planning",
    )

    days = {}
    for i, topic in enumerate(topics):
        subject = topic["subject"]
        chapter = topic["chapter"]
        days[str(i)] = {"day_bn": BN_WEEKDAY_NAMES[i], "subject": subject, "chapter": chapter}

    state = remember_planned_topics(state, topics, monday)

    state.update({
        "exam_focus": exam_focus,
        "week_start_date": monday.isoformat(),
        "week_label_bn": format_week_label_bn(monday),
        "days": days,
        "planner_version": TOPIC_PLANNER_VERSION,
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
    return f"""You are an expert Bengali MCQ question setter for Indian and West Bengal competitive exams.
Target difficulty: {exam_focus}

Create exactly {num_questions} MCQs for:
Subject: {subject}
Chapter/topic: {chapter}

Rules:
1. The question, explanation, and detailed_explanation must be in Bengali.
   If the subject is English grammar/vocabulary, the tested word/sentence/options may contain English,
   but the instruction/explanation must still be Bengali.
2. Exactly 4 plausible options per question.
3. correct_index is 0, 1, 2, or 3.
4. Questions must match WBCS/WBPSC/WB Police/Kolkata Police/SSC/Railway/Banking/TET exam style.
5. explanation: one short Bengali sentence.
6. detailed_explanation: 2-4 useful Bengali sentences for result review.
7. Avoid vague trivia. Ask exam-relevant, factual, unambiguous questions.
8. Return only the JSON array described by the schema.
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
        "📌 <b>এই সপ্তাহের Competitive Exam Topic Plan</b>",
        f"🎯 <b>লক্ষ্য পরীক্ষা:</b> {esc(state['exam_focus'])}",
        f"🗓️ <b>{esc(state['week_label_bn'])}</b>",
        "",
    ]
    for i in range(6):
        d = state["days"][str(i)]
        lines.append(f"<b>{esc(d['day_bn'])}</b> · {esc(d['subject'])} — {esc(d['chapter'])}")
    lines.extend([
        "",
        "ধীরে ধীরে History, Polity, Geography, Science, Math, Reasoning, Language, Computer, Current Affairs সব গুরুত্বপূর্ণ অংশ কভার হবে।",
        "প্রতিদিনের কুইজ Mini App-এ খুলবে, স্কোর সরাসরি ড্যাশবোর্ডে জমা হবে।",
    ])
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
        "প্রশ্নগুলো competitive-exam practice-এর জন্য সাজানো। "
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
