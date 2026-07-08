# Telegram Quiz Pack Bot

DB-backed Telegram Mini App quiz bot for Bengali government-exam mock tests.
This repo uses the same Supabase schema and raw-event data model as
`telegram_mcq_bot`.

## What Runs

- `bot.py --mode announce` posts the weekly syllabus.
- `bot.py --mode quiz` generates today's quiz pack, stores it in Supabase,
  and posts a Telegram Mini App button.
- `app.py` serves the Mini App, submission API, and leaderboard dashboard.

## Shared Database Tables

- `questions`
- `polls`
- `users`
- `user_attempts`
- `bot_state`
- `personal_review_schedule`

Apply `database/schema.sql` in Supabase before running the bot.

## Local Run

```bash
pip install -r requirements.txt
DEV_ALLOW_UNVERIFIED_TELEGRAM=true uvicorn app:app --reload
```

Generate/post a quiz:

```bash
python bot.py --mode quiz
```

See `DEPLOYMENT_GUIDE.md` for production setup.
