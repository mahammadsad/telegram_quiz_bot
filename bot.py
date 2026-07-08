"""
bot.py — সম্পূর্ণ স্বয়ংক্রিয় (100% automated) WB / Central Govt Exam
Telegram Quiz Bot — Bengali MCQ generator + Telegram Mini App delivery.

--------------------------------------------------------------------------
HOW THIS WORKS (read this before editing anything below)
--------------------------------------------------------------------------
0. NOTHING in this file needs weekly hand-editing. `ensure_current_week()`
   asks Gemini to write next week's chapters itself (grounded in what's
   already been covered, via `syllabus_state.json`), so the syllabus is
   100% AI + script generated — there is no dictionary here to update.

1. Every SUNDAY, `send_sunday_announcement()` first makes sure this week's
   syllabus exists (generating it with Gemini if it doesn't yet), then
   posts it to your Telegram group as a plain formatted text message.

2. Every MONDAY–SATURDAY, `send_daily_quiz()`:
     a. Makes sure this week's syllabus exists (self-healing: if the Sunday
        job hasn't run yet for any reason, it generates it right here).
     b. Looks up today's {subject, chapter} from that syllabus.
     c. Asks Gemini for 10 strict-JSON Bengali MCQs on that chapter.
     d. Writes that quiz as a small plain-JSON file to `quizzes/<id>.json`
        (id = today's date, e.g. "20260709") — no compression, no
        URL-encoding, just a normal static file sitting in the repo.
     e. Posts a message to the group with a button linking to
        `https://t.me/<your-bot>/<your-miniapp-shortname>?startapp=<id>`.
        Because this is a genuine Telegram Mini App **direct link** (not a
        plain external URL), Telegram opens it natively inside the app —
        no "open this link?" prompt, no browser chrome.
     f. index.html (hosted on GitHub Pages) reads that `id` from
        `Telegram.WebApp.initDataUnsafe.start_param`, fetches
        `quizzes/<id>.json` as a normal static asset, and renders/grades
        the quiz entirely in the student's browser.

   WHY NOT JUST PUT THE QUIZ DATA IN THE startapp PARAMETER? Telegram caps
   that parameter at 512 characters, and a 10-question quiz with
   explanations runs well past that even compressed — so the quiz itself
   has to live somewhere else. A plain file in the repo is the simplest
   "somewhere else" that needs no extra hosting or accounts.

3. STATE — `syllabus_state.json` (repo root) is this project's syllabus
   memory: current week's generated chapters plus a short history per
   subject so Gemini doesn't repeat itself. `quizzes/*.json` are a second,
   simpler kind of state — one small file per day's quiz, kept forever
   (they're tiny; a year of them is well under a megabyte). The GitHub
   Actions workflow commits both back to the repo automatically after
   every run that changes them — see the last step in quiz_scheduler.yml.
   You never open or edit these files yourself.

4. LEADERBOARD — bot.py does not touch this at all. index.html and
   dashboard.html write/read scores directly to Firestore from the
   student's browser using the Firebase Web SDK (see DEPLOYMENT_GUIDE.md).
   That keeps bot.py's job narrowly scoped to "write questions, post
   message" — no service-account keys or admin SDKs needed here.

5. SCHEDULING — there are two supported ways to run this script. Pick ONE:

     METHOD A (recommended): GitHub Actions cron
        GitHub triggers a fresh, short-lived run of `python bot.py --mode ...`
        at the times you set in .github/workflows/quiz_scheduler.yml.
        This is what "serverless" actually means in this project — nothing
        needs to stay running. See DEPLOYMENT_GUIDE.md.

     METHOD B: `schedule` library on an always-on machine
        If you'd rather run this on a VPS / Raspberry Pi / home server that
        is on 24/7, use `python bot.py --mode daemon`. This is the classic
        `schedule.every()...` loop. It will NOT work on GitHub Actions,
        because Actions kills the runner as soon as one script finishes —
        there is no "always on" process for `schedule` to keep alive.
        (In this mode, `syllabus_state.json` and `quizzes/` just persist on
        local disk — there's no git commit step, and none is needed.)

--------------------------------------------------------------------------
ENVIRONMENT VARIABLES REQUIRED (see DEPLOYMENT_GUIDE.md for how to set these)
--------------------------------------------------------------------------
  GEMINI_API_KEY         — from https://aistudio.google.com/app/apikey
  TELEGRAM_BOT_TOKEN     — from @BotFather
  TELEGRAM_CHAT_ID       — your group's chat id (negative number, e.g. -100123456789)
  TELEGRAM_BOT_USERNAME  — your bot's @username, WITHOUT the @ (e.g. "wb_quiz_bot")
  MINIAPP_SHORT_NAME     — the short name you gave BotFather in /newapp (e.g. "quiz")
"""

import os
import sys
import json
import time
import html
import random
import logging
import argparse
from datetime import datetime, date, timedelta

import requests
from google import genai
from google.genai import types

# ==========================================================================
# CONFIG
# ==========================================================================

# Gemini model to use for MCQ generation. As of July 2026 this is the current
# free-tier "flash" model. If Google renames/retires it, check the live list
# at https://ai.google.dev/gemini-api/docs/models and update this one line.
GEMINI_MODEL = "gemini-3.5-flash"

NUM_QUESTIONS = 10          # MCQs generated per day
MAX_RETRIES = 4             # retry attempts for Gemini / Telegram calls
RETRY_BASE_DELAY = 3        # seconds; doubles each retry (exponential backoff)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

# Quiz files live in this folder, one per day, e.g. quizzes/20260709.json —
# committed to the repo by quiz_scheduler.yml, served as a plain static file
# by GitHub Pages right alongside index.html.
QUIZZES_DIR = "quizzes"

# Needed to build the Telegram Mini App direct link:
#   https://t.me/<TELEGRAM_BOT_USERNAME>/<MINIAPP_SHORT_NAME>?startapp=<id>
# Neither of these is secret (a bot's username and Mini App short name are
# public by nature), so they're read as plain repo Variables, not Secrets —
# see DEPLOYMENT_GUIDE.md.
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
MINIAPP_SHORT_NAME = os.environ.get("MINIAPP_SHORT_NAME", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("wb_quiz_bot")



# ==========================================================================
# WEEKLY SYLLABUS — 100% self-updating, nothing here to edit by hand
# ==========================================================================
# The old version of this file had a WEEKLY_SYLLABUS dict you had to edit
# every Sunday. That's gone. Instead:
#   - The Monday-Friday SUBJECT for each weekday is a fixed timetable (below)
#     — like a school routine, this doesn't change week to week.
#   - The actual CHAPTER taught under each subject is chosen by Gemini every
#     week (see `generate_weekly_chapters()`), grounded in what's already
#     been covered (`syllabus_state.json`) so it progresses through the real
#     syllabus instead of repeating itself.
#   - Saturday is always Current Affairs — "recent events" is inherently
#     always-fresh, so that slot never needs new chapter text.
#
# `days` dict keys follow Python's `datetime.weekday()` convention:
#   0 = Monday, 1 = Tuesday, 2 = Wednesday, 3 = Thursday, 4 = Friday, 5 = Saturday
# (Sunday/6 is intentionally absent — that's announcement day, not quiz day.)

DEFAULT_EXAM_FOCUS = "WBCS প্রিলিমিনারি ও WBPSC গ্রুপ-ডি"

BN_WEEKDAY_NAMES = {
    0: "সোমবার", 1: "মঙ্গলবার", 2: "বুধবার",
    3: "বৃহস্পতিবার", 4: "শুক্রবার", 5: "শনিবার",
}

# Fixed Monday->Friday subject timetable. Gemini fills in the chapter under
# each of these every week; the subject names themselves never change.
SUBJECTS_MON_TO_FRI = ["ইতিহাস", "ভূগোল", "সাধারণ বিজ্ঞান", "গণিত", "রাজনীতি বিজ্ঞান"]

CURRENT_AFFAIRS_SUBJECT = "কারেন্ট অ্যাফেয়ার্স"
CURRENT_AFFAIRS_CHAPTER = "সাম্প্রতিক জাতীয় ও আন্তর্জাতিক ঘটনা"

SYLLABUS_STATE_PATH = "syllabus_state.json"

BN_MONTHS = [
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
    "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
]
_BN_DIGIT_MAP = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn_num(n: int) -> str:
    """Converts an int to a string using Bengali digits (0-9 -> ০-৯)."""
    return str(n).translate(_BN_DIGIT_MAP)


def format_week_label_bn(monday: date) -> str:
    """Builds a label like '৭ – ১৩ জুলাই, ২০২৬' for the Mon-Sat span
    starting on `monday`, handling the (rarer) case where the week crosses
    a month or year boundary."""
    saturday = monday + timedelta(days=5)
    if monday.year == saturday.year:
        if monday.month == saturday.month:
            return (f"{bn_num(monday.day)} – {bn_num(saturday.day)} "
                     f"{BN_MONTHS[monday.month - 1]}, {bn_num(monday.year)}")
        return (f"{bn_num(monday.day)} {BN_MONTHS[monday.month - 1]} – "
                f"{bn_num(saturday.day)} {BN_MONTHS[saturday.month - 1]}, {bn_num(monday.year)}")
    return (f"{bn_num(monday.day)} {BN_MONTHS[monday.month - 1]}, {bn_num(monday.year)} – "
            f"{bn_num(saturday.day)} {BN_MONTHS[saturday.month - 1]}, {bn_num(saturday.year)}")


# --------------------------------------------------------------------------
# STATE PERSISTENCE — read/write syllabus_state.json
# --------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(SYLLABUS_STATE_PATH):
        try:
            with open(SYLLABUS_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Couldn't read {SYLLABUS_STATE_PATH} ({e}); starting fresh.")
    return {"exam_focus": DEFAULT_EXAM_FOCUS, "history": {}}


def save_state(state: dict) -> None:
    with open(SYLLABUS_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    log.info(f"Wrote {SYLLABUS_STATE_PATH} (the GitHub Action will commit this automatically).")


# --------------------------------------------------------------------------
# GEMINI — WEEKLY CHAPTER GENERATION (this replaces manual syllabus editing)
# --------------------------------------------------------------------------

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
        covered_text = "; ".join(covered) if covered else "(এখনও কিছু কভার করা হয়নি — এটাই প্রথম সপ্তাহ)"
        blocks.append(f'- বিষয়: "{subject}" | ইতিমধ্যে পড়ানো চ্যাপ্টার: {covered_text}')
    subjects_text = "\n".join(blocks)

    return f"""তুমি একজন অভিজ্ঞ প্রশ্নপত্র/সিলেবাস পরিকল্পনাকারী, যে West Bengal সরকারি
চাকরির পরীক্ষার্থীদের (WBCS, WBPSC, WB Police, Group-D/C, Railway) জন্য
সাপ্তাহিক পড়ার পরিকল্পনা তৈরি করে।

লক্ষ্য পরীক্ষা: {exam_focus}

নিচের {len(SUBJECTS_MON_TO_FRI)}টি বিষয়ের প্রতিটির জন্য আগামী সপ্তাহে পড়ানোর মতো
ঠিক ১টি করে নতুন চ্যাপ্টার/টপিক বেছে নাও। প্রকৃত WBCS/WBPSC প্রিলিমস সিলেবাসের
কাঠামো অনুসরণ করে যৌক্তিকভাবে এগিয়ে যাও (সহজ ভিত্তি থেকে ধীরে ধীরে গভীর
টপিকের দিকে):

{subjects_text}

কঠোর নিয়ম:
1. প্রতিটি বিষয়ের জন্য অবশ্যই তার "ইতিমধ্যে পড়ানো চ্যাপ্টার" তালিকা থেকে সম্পূর্ণ
   আলাদা এবং নতুন একটি চ্যাপ্টার বেছে নিতে হবে।
2. আউটপুট অবশ্যই ঠিক {len(SUBJECTS_MON_TO_FRI)}টি অবজেক্ট সম্বলিত একটি JSON array
   হতে হবে, ঠিক এই ক্রমে: {", ".join(SUBJECTS_MON_TO_FRI)}।
3. প্রতিটি অবজেক্টে থাকবে "subject" (উপরের নাম হুবহু, অপরিবর্তিত) এবং "chapter"
   (নির্দিষ্ট, সংক্ষিপ্ত, বাংলায় লেখা চ্যাপ্টারের নাম)।
4. শুধুমাত্র JSON array রিটার্ন করো — কোনো ভূমিকা, ব্যাখ্যা, বা markdown fence ছাড়া।
"""


def generate_weekly_chapters(exam_focus: str, history: dict) -> list:
    """Asks Gemini for one fresh chapter per Mon-Fri subject. Returns a list
    of chapter strings in the same order as SUBJECTS_MON_TO_FRI."""
    client = genai.Client()
    prompt = _build_syllabus_prompt(exam_focus, history)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WEEKLY_CHAPTERS_SCHEMA,
            temperature=0.8,
        ),
    )

    raw = json.loads(response.text)
    chapters = [str(item.get("chapter", "")).strip() for item in raw if str(item.get("chapter", "")).strip()]

    if len(chapters) != len(SUBJECTS_MON_TO_FRI):
        raise ValueError(
            f"Expected {len(SUBJECTS_MON_TO_FRI)} chapters from Gemini, got {len(chapters)}."
        )
    return chapters


def ensure_current_week(state: dict) -> tuple:
    """Makes sure `state` has a syllabus for the Mon-Sat week containing
    today. If it's missing or stale (i.e. we're in a new week), generates
    one with Gemini, updates history, saves state to disk, and returns
    (state, True). If it's already current, returns (state, False) and
    touches nothing — this is what keeps a normal Mon-Sat quiz run from
    calling Gemini twice."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    if state.get("week_start_date") == monday.isoformat() and state.get("days"):
        return state, False

    log.info("This week's syllabus is missing or stale — generating a new one with Gemini...")
    exam_focus = state.get("exam_focus") or DEFAULT_EXAM_FOCUS
    history = state.get("history") or {}

    new_chapters = retry_with_backoff(
        generate_weekly_chapters, exam_focus, history,
        what="Gemini weekly syllabus generation",
    )

    days = {}
    for i, subject in enumerate(SUBJECTS_MON_TO_FRI):
        chapter = new_chapters[i]
        days[str(i)] = {"day_bn": BN_WEEKDAY_NAMES[i], "subject": subject, "chapter": chapter}
        history.setdefault(subject, []).append(chapter)
        history[subject] = history[subject][-20:]  # keep ~20 weeks of memory per subject
    days["5"] = {"day_bn": BN_WEEKDAY_NAMES[5], "subject": CURRENT_AFFAIRS_SUBJECT, "chapter": CURRENT_AFFAIRS_CHAPTER}

    state["exam_focus"] = exam_focus
    state["history"] = history
    state["week_start_date"] = monday.isoformat()
    state["week_label_bn"] = format_week_label_bn(monday)
    state["days"] = days

    save_state(state)
    log.info(f"Generated syllabus for the week of {state['week_label_bn']}.")
    return state, True


# ==========================================================================
# RETRY HELPER — wraps flaky network calls (Gemini 429s, Telegram hiccups)
# ==========================================================================

def retry_with_backoff(fn, *args, retries=MAX_RETRIES, base_delay=RETRY_BASE_DELAY, what="operation", **kwargs):
    """Calls fn(*args, **kwargs), retrying with exponential backoff + jitter
    on any exception. Re-raises the last error if every attempt fails."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            wait = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
            log.warning(f"{what} failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                log.info(f"Retrying {what} in {wait:.1f}s...")
                time.sleep(wait)
    log.error(f"{what} failed after {retries} attempts — giving up.")
    raise last_err


# ==========================================================================
# GEMINI — MCQ GENERATION (strict JSON via response_schema)
# ==========================================================================

MCQ_JSON_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "question": {"type": "STRING"},
            "options": {"type": "ARRAY", "items": {"type": "STRING"}},
            "correct_index": {"type": "INTEGER"},
            "explanation": {"type": "STRING"},
        },
        "required": ["question", "options", "correct_index", "explanation"],
    },
}


def _build_mcq_prompt(subject: str, chapter: str, exam_focus: str, num_questions: int) -> str:
    return f"""You are an expert question-setter for West Bengal government job
competitive exams (WBCS, WBPSC, WB Police, WB Group-D/C, Railway NTPC/Group-D,
SSC), writing at the difficulty level of: {exam_focus}.

Write exactly {num_questions} multiple-choice questions for the subject
"{subject}", specifically on this chapter/topic: "{chapter}".

STRICT RULES:
1. The "question", every string inside "options", and the "explanation" MUST
   be written entirely in the Bengali language (বাংলা). Do not use English,
   except for globally standard proper nouns/abbreviations that Bengali exam
   papers conventionally keep in Roman script (e.g. "GST", "ISRO", "UNESCO").
2. Each question must have EXACTLY 4 options.
3. "correct_index" is the 0-based index (0, 1, 2, or 3) of the correct entry
   inside that question's "options" array.
4. Match the real difficulty and style of actual WBCS/WBPSC/SSC/Railway past
   papers — precise and factual, not generic trivia-quiz style.
5. Make all 4 options plausible; avoid options that are obviously silly or
   unrelated — good distractors are part of what makes this useful practice.
6. "explanation" must be a short 1–2 sentence Bengali explanation of why the
   correct option is correct, useful for a student revising afterward.
7. Do not repeat the same fact or question twist across the {num_questions}
   questions.
8. Return ONLY the JSON array described by the schema. No preamble, no
   markdown code fences, no commentary outside the JSON.
"""


def generate_mcqs(subject: str, chapter: str, exam_focus: str, num_questions: int = NUM_QUESTIONS) -> list:
    """Calls Gemini and returns a validated list of MCQ dicts:
    [{"question": str, "options": [4 strings], "correct_index": int, "explanation": str}, ...]
    """
    # genai.Client() automatically reads GEMINI_API_KEY (or GOOGLE_API_KEY)
    # from the environment — no need to pass the key explicitly.
    client = genai.Client()

    prompt = _build_mcq_prompt(subject, chapter, exam_focus, num_questions)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MCQ_JSON_SCHEMA,
            temperature=0.9,
        ),
    )

    raw = json.loads(response.text)

    # --- sanitize / validate, in case the model drifts slightly from schema ---
    clean = []
    for item in raw:
        try:
            q = str(item["question"]).strip()
            opts = [str(o).strip() for o in item["options"]]
            idx = int(item["correct_index"])
            expl = str(item.get("explanation", "")).strip()
            if q and len(opts) == 4 and 0 <= idx <= 3:
                clean.append({"question": q, "options": opts, "correct_index": idx, "explanation": expl})
        except (KeyError, ValueError, TypeError):
            continue  # skip any malformed entry rather than crashing the whole run

    if len(clean) < 5:
        # Don't post a broken/near-empty quiz to real students — fail loudly instead.
        raise ValueError(f"Gemini returned only {len(clean)} usable questions (need at least 5).")

    return clean


# ==========================================================================
# QUIZ FILE + MINI APP LINK — this replaces the old zlib+base64 URL encoding
# ==========================================================================
# The quiz now travels as a small plain-JSON file (quizzes/<id>.json)
# instead of being packed into the URL. The Telegram message links to a
# Mini App **direct link** (https://t.me/<bot>/<shortname>?startapp=<id>),
# which Telegram opens natively — no external-link warning, no browser
# chrome — because it recognizes the t.me/ domain as its own Mini App
# launch mechanism rather than an arbitrary external URL.

def quiz_id_for_date(d: date) -> str:
    """A short id safe for the startapp parameter (only A-Z a-z 0-9 _ -
    are allowed there) and safe as a filename."""
    return d.strftime("%Y%m%d")


def save_quiz_file(quiz_id: str, questions: list, meta: dict) -> str:
    os.makedirs(QUIZZES_DIR, exist_ok=True)
    payload = {
        "meta": meta,
        "qs": [
            {"q": item["question"], "o": item["options"], "a": item["correct_index"], "e": item["explanation"]}
            for item in questions
        ],
    }
    path = os.path.join(QUIZZES_DIR, f"{quiz_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    log.info(f"Wrote {path} ({os.path.getsize(path)} bytes) — the GitHub Action will commit this automatically.")
    return path


def validate_miniapp_config() -> None:
    """Fails fast with one clear message instead of letting a missing
    TELEGRAM_BOT_USERNAME / MINIAPP_SHORT_NAME surface as a confusing
    Telegram 400 error, or a link that opens as a generic external page."""
    problems = []
    if not TELEGRAM_BOT_USERNAME:
        problems.append(
            "TELEGRAM_BOT_USERNAME is not set (your bot's @username, without the @, "
            "e.g. \"wb_quiz_bot\")."
        )
    if not MINIAPP_SHORT_NAME:
        problems.append(
            "MINIAPP_SHORT_NAME is not set (the short name you gave BotFather when "
            "you ran /newapp)."
        )
    if problems:
        raise RuntimeError(
            "Mini App isn't fully configured yet:\n- " + "\n- ".join(problems) +
            "\nSee DEPLOYMENT_GUIDE.md → 'Register your Mini App with BotFather'."
        )


def build_miniapp_url(quiz_id: str) -> str:
    return f"https://t.me/{TELEGRAM_BOT_USERNAME}/{MINIAPP_SHORT_NAME}?startapp={quiz_id}"


# ==========================================================================
# TELEGRAM DELIVERY (plain HTTPS calls — no bot framework needed for a
# script that only ever SENDS messages and never listens for updates)
# ==========================================================================

def esc(text) -> str:
    """Escape text before dropping it into a parse_mode='HTML' message.
    Chapter/subject names sometimes contain '&', '<', '>' etc. — without
    this, Telegram rejects the whole message with a 400 'can't parse
    entities' error instead of just showing the raw character."""
    return html.escape(str(text), quote=False)


def telegram_api(method: str, payload: dict) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = TELEGRAM_API_BASE.format(token=token, method=method)
    resp = requests.post(url, json=payload, timeout=30)
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {result}")
    return result


def send_sunday_announcement():
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    state = load_state()
    state, _ = ensure_current_week(state)  # generates next week's chapters via Gemini if needed
    days = state["days"]

    lines = [
        "📢 <b>এই সপ্তাহের মক টেস্ট সিলেবাস</b>",
        f"🎯 <b>লক্ষ্য পরীক্ষা:</b> {esc(state['exam_focus'])}",
        f"🗓️ {esc(state['week_label_bn'])}",
        "",
    ]
    for i in range(6):  # Monday(0) .. Saturday(5)
        d = days[str(i)]
        lines.append(f"<b>{esc(d['day_bn'])}:</b> {esc(d['subject'])} — {esc(d['chapter'])}")
    lines.append("")
    lines.append("✅ প্রতিদিন সন্ধ্যায় সংশ্লিষ্ট চ্যাপ্টার থেকে ১০টি প্রশ্নের কুইজ পোস্ট হবে। প্রস্তুতি নিয়ে রাখো! 💪")

    text = "\n".join(lines)

    retry_with_backoff(
        telegram_api, "sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        what="Sunday announcement",
    )
    log.info("Sunday syllabus announcement sent.")


def send_daily_quiz():
    today_idx = datetime.now().weekday()  # 0=Mon .. 6=Sun

    if today_idx == 6:
        log.info("Today is Sunday — no quiz scheduled. Skipping.")
        return

    validate_miniapp_config()  # fail fast, before any Gemini/Telegram calls

    state = load_state()
    state, _ = ensure_current_week(state)  # self-healing: generates the week if Sunday's job hasn't run

    day_info = state["days"][str(today_idx)]
    subject, chapter = day_info["subject"], day_info["chapter"]
    exam_focus = state["exam_focus"]

    log.info(f"Generating {NUM_QUESTIONS} MCQs for {subject} / {chapter} ...")
    questions = retry_with_backoff(
        generate_mcqs, subject, chapter, exam_focus, NUM_QUESTIONS,
        what="Gemini MCQ generation",
    )
    log.info(f"Got {len(questions)} validated questions from Gemini.")

    quiz_id = quiz_id_for_date(date.today())
    meta = {"subject": subject, "chapter": chapter, "date": date.today().isoformat(), "quiz_id": quiz_id}
    save_quiz_file(quiz_id, questions, meta)
    quiz_url = build_miniapp_url(quiz_id)
    log.info(f"Mini App URL: {quiz_url}")

    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    text = (
        "📝 <b>আজকের মক টেস্ট প্রস্তুত!</b>\n\n"
        f"📚 <b>বিষয়:</b> {esc(subject)}\n"
        f"📖 <b>চ্যাপ্টার:</b> {esc(chapter)}\n"
        f"🔢 <b>প্রশ্ন সংখ্যা:</b> {len(questions)}টি\n\n"
        "নিচের বাটনে ক্লিক করে আজকের কুইজ শুরু করো। শুভকামনা! 🎯"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": f"✍️ আজকের কুইজ শুরু করো — {day_info['day_bn']}", "url": quiz_url}
        ]]
    }

    retry_with_backoff(
        telegram_api, "sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard},
        what="Daily quiz post",
    )
    log.info("Daily quiz posted to Telegram.")


# ==========================================================================
# METHOD B (optional/alternative) — always-on `schedule` library daemon
# ==========================================================================
# Only use this if bot.py is running on a machine that is ON 24/7 (a VPS,
# Raspberry Pi, home PC left running, Oracle Cloud free-tier VM, etc).
# It will NOT work as a GitHub Actions job. Set your server's timezone to
# Asia/Kolkata (or adjust the times below) before relying on this.

def _safe_run(fn):
    try:
        fn()
    except Exception:
        log.exception(f"Unhandled error while running {fn.__name__}")


def run_scheduler_daemon():
    import schedule  # imported here so METHOD A users never need this package

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

    log.info(
        "Scheduler daemon started (schedule library). Times are evaluated in "
        "the machine's LOCAL timezone — set TZ=Asia/Kolkata in your "
        "environment if this server isn't already on IST."
    )
    while True:
        schedule.run_pending()
        time.sleep(30)


# ==========================================================================
# ENTRY POINT
# ==========================================================================

def main():
    parser = argparse.ArgumentParser(description="WB Govt Exam Telegram Quiz Bot")
    parser.add_argument(
        "--mode",
        choices=["announce", "quiz", "daemon"],
        required=True,
        help=(
            "announce = post Sunday syllabus | "
            "quiz = generate + post today's MCQ quiz | "
            "daemon = run the always-on `schedule` loop (needs a 24/7 host, NOT GitHub Actions)"
        ),
    )
    args = parser.parse_args()

    try:
        if args.mode == "announce":
            send_sunday_announcement()
        elif args.mode == "quiz":
            send_daily_quiz()
        elif args.mode == "daemon":
            run_scheduler_daemon()
    except Exception:
        log.exception("Fatal error — exiting with non-zero status so GitHub Actions marks this run as failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
