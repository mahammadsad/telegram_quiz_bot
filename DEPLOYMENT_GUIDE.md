# WB Exam Quiz Pack Bot - Deployment Guide

This repo now uses the same Supabase/Postgres architecture as
`mahammadsad/telegram_mcq_bot`:

- `questions`: shared question bank
- `polls`: per-question quiz-pack delivery/session records
- `users`: Telegram Mini App users
- `user_attempts`: raw answer events
- `bot_state`: operational state, including weekly syllabus memory

Firebase, Firestore rules, committed quiz JSON files, and committed syllabus
state are no longer part of this project.

## 1. Create / Reuse Supabase

Use the same Supabase project as repo_1 if you want unified analytics.

1. Open Supabase SQL Editor.
2. Paste and run `database/schema.sql`.
3. In Project Settings -> API, copy:
   - `SUPABASE_URL`
   - `service_role` key as `SUPABASE_SERVICE_KEY`

Use the service role key only on GitHub Actions and the FastAPI server. Never
put it in browser JavaScript.

## 2. Environment Variables

Set these on the API host and GitHub Actions:

```bash
GEMINI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_BOT_USERNAME=your_bot_username_without_at
MINIAPP_SHORT_NAME=quiz
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
```

Optional:

```bash
GEMINI_MODEL=gemini-2.5-flash
DEV_ALLOW_UNVERIFIED_TELEGRAM=false
CORS_ALLOWED_ORIGINS=https://your-pages-domain.example
```

## 3. Deploy the Mini App API

Deploy this repo as a Python web service. The start command is:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

The included `Procfile` works for hosts that support it. After deploy, your
Mini App URL will be:

```text
https://your-api-domain.example/
```

The same server also serves:

- `/` -> quiz Mini App
- `/dashboard.html` -> leaderboard dashboard
- `/api/quiz/{quiz_id}` -> question fetch
- `/api/quiz/{quiz_id}/submit` -> verified answer submission
- `/api/leaderboard` -> live leaderboard

## 4. Register the Telegram Mini App

In BotFather:

1. Run `/newapp` or edit the existing app with `/myapps`.
2. Set the Web App URL to your deployed API root URL, for example:
   `https://your-api-domain.example/`
3. Save the short name as `MINIAPP_SHORT_NAME`.

`bot.py` posts links in this format:

```text
https://t.me/<TELEGRAM_BOT_USERNAME>/<MINIAPP_SHORT_NAME>?startapp=<quiz_id>
```

## 5. GitHub Actions Scheduler

The workflow `.github/workflows/main.yml` runs:

- Sunday 20:00 IST: `python bot.py --mode announce`
- Monday-Saturday 18:30 IST: `python bot.py --mode quiz`

Add these GitHub Secrets:

- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

Add these GitHub Variables:

- `TELEGRAM_BOT_USERNAME`
- `MINIAPP_SHORT_NAME`

The workflow no longer commits generated files. Quiz packs and syllabus state
are written to Supabase.

## 6. Import Old JSON Quiz Packs

If you still have old `quizzes/*.json` files, import them once:

```bash
python scripts/import_legacy_quizzes.py
```

The script writes each pack into `questions` and `polls`. It is safe to skip
if you do not need old packs.

## 7. Local Development

Install and run:

```bash
pip install -r requirements.txt
DEV_ALLOW_UNVERIFIED_TELEGRAM=true uvicorn app:app --reload
```

Open a known quiz id:

```text
http://127.0.0.1:8000/?quiz=20260708
```

Generate/post today:

```bash
python bot.py --mode quiz
```

## 8. Data Flow

1. `bot.py --mode quiz` generates questions with Gemini.
2. Each unique MCQ is inserted or reused in `questions`.
3. Each quiz-pack question gets a delivery row in `polls` with
   `bot_type='mock_test'` and `run_slot=<quiz_id>`.
4. The Telegram button opens the Mini App with `startapp=<quiz_id>`.
5. The Mini App fetches questions from the API without correct answers.
6. On submit, the API verifies Telegram `initData`, upserts the user, and
   writes one raw `user_attempts` row per answered question.
7. The dashboard computes leaderboard totals from raw attempts at read time.
