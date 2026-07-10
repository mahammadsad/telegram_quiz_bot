# Telegram Subject Quiz Bot

Production-oriented Bengali Telegram Mini App quiz system. Every day it schedules exactly one 10-question quiz for each of 13 canonical subjects. A scheduled process handles one subject, saves validated content before delivery, and posts through a numeric Telegram `message_thread_id`.

## Daily schedule

| Canonical key | Telegram forum name | IST | UTC | GitHub cron |
|---|---|---:|---:|---|
| `computer` | কম্পিউটার শিক্ষা | 07:00 | 01:30 | `30 1 * * *` |
| `bengali` | বাংলা | 08:00 | 02:30 | `30 2 * * *` |
| `reasoning` | রিজনিং | 09:00 | 03:30 | `30 3 * * *` |
| `mathematics` | গণিত | 10:00 | 04:30 | `30 4 * * *` |
| `english` | ইংরেজি | 11:00 | 05:30 | `30 5 * * *` |
| `miscellaneous` | বিবিধ | 12:00 | 06:30 | `30 6 * * *` |
| `polity` | সংবিধান ও প্রশাসন | 13:00 | 07:30 | `30 7 * * *` |
| `geography` | ভূগোল | 14:00 | 08:30 | `30 8 * * *` |
| `science` | বিজ্ঞান | 15:00 | 09:30 | `30 9 * * *` |
| `economics` | অর্থনীতি | 16:00 | 10:30 | `30 10 * * *` |
| `history` | ইতিহাস | 17:00 | 11:30 | `30 11 * * *` |
| `environment` | পরিবেশ | 18:00 | 12:30 | `30 12 * * *` |
| `current-affairs` | কারেন্ট অ্যাফেয়ার্স | 19:00 | 13:30 | `30 13 * * *` |
| recovery only | জেনারেল তথ্য/administrator | 20:30 | 15:00 | `0 15 * * *` |

`general` (`জেনারেল তথ্য`) is announcement-only and is never scheduled as a quiz. The mapping lives only in `config/subjects.py`; workflow cron expressions map directly to canonical keys, so a late GitHub runner cannot select the wrong subject from its wall clock.

## Data flow

1. The job validates the canonical subject and complete numeric forum routing.
2. It builds `YYYYMMDD-<subject-key>`, checks `quiz_runs`, and reuses a saved pack only after verifying exactly 10 questions and its checksum.
3. `chapter_selector` chooses from that subject's curated catalogue, preferring unseen chapters and then 3/7/14/30-day review windows.
4. The Gemini provider pool makes one normal generation request, strictly validates all 10 questions, and permits one structured repair request only for malformed JSON.
5. Questions and `polls` delivery rows are stored, a public answer-free fallback is exported, and the run becomes `generated`.
6. Telegram receives `sendMessage` with the subject's numeric `message_thread_id`. Only a successful response can mark the run `posted` and store message metadata.
7. The Mini App loads a read-only public payload. FastAPI verifies Telegram `initData`, writes/upserts the user and answered `user_attempts`, stores one immutable `quiz_submissions` row, and calculates score/rank from server-side answers.

The public GET endpoint never invokes Gemini. New quiz IDs are always subject-scoped; historical `YYYYMMDD` IDs remain readable when a DB record or public static file exists.

## Forum thread IDs

Configure a complete server-side JSON object (the numbers below are placeholders):

```text
TELEGRAM_FORUM_TOPICS_JSON={"computer":101,"bengali":102,"reasoning":103,"mathematics":104,"english":105,"miscellaneous":106,"polity":107,"geography":108,"science":109,"economics":110,"history":111,"environment":112,"current-affairs":113}
```

IDs must be unique positive JSON integers. Missing keys, extra keys, booleans, strings, zero, negatives, and duplicates fail before Gemini is called. Runtime routing never matches Bengali display names.

To discover IDs, set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally comma-separated `TELEGRAM_ADMIN_USER_IDS`, then run:

```bash
python scripts/discover_topic_ids.py
```

An administrator sends `/topicid history`, `/topicid geography`, etc. inside the matching forum thread. The utility checks the configured chat and either the configured allow-list or Telegram chat-administrator status, advances the long-poll offset, and replies with the canonical key, Bengali name, chat ID, thread ID, and a copyable JSON snippet. It never prints the bot token. `TELEGRAM_GENERAL_THREAD_ID` is optional; when absent, announcements omit the thread parameter.

## Gemini failover

Resolution is primary, then secondary; legacy `GEMINI_API_KEY` is used only if neither new key exists. A successful primary call never alternates to secondary and the second key is not quota expansion.

| Category | Behaviour |
|---|---|
| 408/429/5xx, timeout, unavailable, transient network | Retry current provider with bounded exponential backoff/jitter; after attempts, cool it down and fail over |
| 401 or key/project-specific 403 | Mark current provider invalid for the process and fail over immediately |
| 400/invalid schema or argument | Stop; do not spend the secondary provider |
| confirmed missing/unavailable model | Try fallback model on the same provider, then next provider |
| safety block | Stop; never change keys to bypass safety |

Provider health is process-local (`healthy`, `cooling_down`, `invalid`); only safe provider labels, model names, categories, and status codes are logged. Keys and raw responses are never logged.

## Commands

```bash
python bot.py --mode subject-quiz --subject history
python bot.py --mode subject-quiz --subject history --force-post
python bot.py --mode subject-quiz --subject history --force-regenerate
python bot.py --mode recover-missed-quizzes
python bot.py --mode announce
python bot.py --mode preflight
```

In GitHub Actions, choose `Run workflow` and `mode=preflight` to validate
required secret presence and forum-routing structure without generating or
posting anything.

`--force-post` requires and reposts a checksum-valid saved quiz without Gemini. `--force-regenerate` explicitly replaces the delivery content; the two flags are mutually exclusive. Recovery considers today's IST schedule, skips future and posted subjects, posts valid generated content first, and generates only genuinely missing/corrupt content.

## Database and local API

For a new database run `database/schema.sql`. For an existing installation run only `database/migrations/002_subject_quiz_runs.sql` in the Supabase SQL Editor; it is additive and idempotent.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DEV_ALLOW_UNVERIFIED_TELEGRAM=true uvicorn app:app --reload
pytest -q
```

Submission JSON:

```json
{"initData":"<Telegram WebApp initData>","answers":[0,2,1,null,3,0,1,2,3,0]}
```

Endpoints:

- `GET /api/quiz/{quiz_id}` — questions/options only; read-only.
- `POST /api/quiz/{quiz_id}/submit` — authenticated immutable submission and answer review.
- `GET /api/quiz/{quiz_id}/leaderboard?limit=20` — isolated score board ordered by score descending, completion time ascending.
- `GET /api/leaderboard` — backward-compatible global dashboard.
- `GET /api/health` — safe configuration booleans; it consumes no Gemini quota.

To confirm public fallbacks contain no answers:

```bash
rg 'correct_index|correct_option|detailed_explanation|"a"\s*:|"e"\s*:' quizzes/
```

The command should produce no output. Never put a Supabase service key, Gemini key, bot token, signed init data, answer key, or private thread mapping in frontend code or committed quiz JSON.
