# Deployment Guide

## 1. Apply the Supabase migration

Existing projects: open Supabase SQL Editor and run `database/migrations/002_subject_quiz_runs.sql`. New projects can run `database/schema.sql`. Both are safe to rerun and preserve existing `questions`, `polls`, `users`, and `user_attempts`.

The migration adds:

- `quiz_runs`: date-subject lifecycle, checksum, provider/model, safe error, and Telegram response metadata; unique `(quiz_date, subject_key)`.
- `chapter_history`: deterministic chapter history; unique `(subject_key, selected_for)`.
- `quiz_submissions`: one immutable completion per `(quiz_id, user_id)`, including the 10-position answer array.
- recovery, chapter, leaderboard, and `polls(run_slot)` indexes.

`user_attempts` already has unique `(user_id, poll_id)`. Answered questions create raw attempt rows; `null` positions remain `null` in `quiz_submissions.answers` and do not invent attempt choices.

## 2. GitHub secrets and variables

Required GitHub Secrets:

```text
GEMINI_API_KEY_PRIMARY
GEMINI_API_KEY_SECONDARY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_FORUM_TOPICS_JSON
SUPABASE_URL
SUPABASE_SERVICE_KEY
```

Optional GitHub Secrets:

```text
TELEGRAM_GENERAL_THREAD_ID
TELEGRAM_ADMIN_CHAT_ID
TELEGRAM_ADMIN_USER_IDS
```

GitHub Variables:

```text
TELEGRAM_BOT_USERNAME
MINIAPP_SHORT_NAME
```

The workflow has 13 exact UTC subject crons plus `0 15 * * *` for recovery. It maps `github.event.schedule` directly, runs a sanitized preflight, and stages only `quizzes/????????-*.json`. Manual examples:

```text
mode=subject-quiz, subject=history, force_post=false, force_regenerate=false
mode=subject-quiz, subject=history, force_post=true, force_regenerate=false
mode=subject-quiz, subject=history, force_post=false, force_regenerate=true
mode=recover-missed-quizzes
mode=preflight
```

Run `mode=preflight` first. It performs no Gemini request and posts no Telegram
message; it exits nonzero when required runtime configuration is incomplete or
the migration `002` tables are unavailable through Supabase.

## 3. Render environment

Required:

```text
SUPABASE_URL
SUPABASE_SERVICE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_BOT_USERNAME
MINIAPP_SHORT_NAME
TELEGRAM_FORUM_TOPICS_JSON
GEMINI_API_KEY_PRIMARY
GEMINI_API_KEY_SECONDARY
GEMINI_MODEL_PRIMARY=gemini-2.5-flash-lite
GEMINI_MODEL_FALLBACK=gemini-2.5-flash
GEMINI_FAILOVER_ENABLED=true
GEMINI_MAX_ATTEMPTS_PER_KEY=2
GEMINI_REQUEST_TIMEOUT_SECONDS=120
GEMINI_KEY_COOLDOWN_SECONDS=900
GEMINI_BACKOFF_BASE_SECONDS=2
GEMINI_MAX_BACKOFF_SECONDS=60
```

Optional:

```text
TELEGRAM_GENERAL_THREAD_ID
TELEGRAM_ADMIN_CHAT_ID
TELEGRAM_ADMIN_USER_IDS
DEV_ALLOW_UNVERIFIED_TELEGRAM=false
CORS_ALLOWED_ORIGINS
```

Keep `DEV_ALLOW_UNVERIFIED_TELEGRAM=false` in production. Start the web service with:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Point the BotFather Mini App URL at the FastAPI root and set the public bot username/short name. Secrets must remain server-side environment values.

## 4. Production verification

1. Run `python scripts/discover_topic_ids.py`. In every Telegram forum thread send `/topicid <canonical-key>`, then combine the 13 snippets into `TELEGRAM_FORUM_TOPICS_JSON`.
2. Run `python bot.py --mode preflight`; it prints only configured true/false flags.
3. Run `python bot.py --mode subject-quiz --subject history`.
4. In `quiz_runs`, confirm `20260710-history`-style ID, `question_count=10`, checksum, `status=posted`, and the returned numeric chat/thread/message IDs.
5. Confirm the Telegram message is inside the ইতিহাস thread and opens `startapp=<date>-history`.
6. In the Mini App, confirm exactly 10 questions render and the loading/retry states work.
7. Submit `{initData, answers}`. Confirm the authenticated Telegram user in `users`, one `user_attempts` row for every non-null answer, and one `quiz_submissions` row.
8. Open `/api/quiz/<quiz-id>/leaderboard`; verify only that quiz's users appear once, ordered by score then completion time.
9. Fetch `/api/quiz/<quiz-id>` and the matching `quizzes/*.json`; verify there are no correct indexes or explanations.
10. Temporarily replace only `GEMINI_API_KEY_PRIMARY` with an invalid value and run a new due test subject. Confirm safe logs show primary key failure followed by `provider=secondary` success. Never paste either key into logs or commands captured by history.
11. Restore the real primary key, run another new subject/date, and confirm primary succeeds without calling secondary.
12. Search logs for the exact known secret values using the hosting provider's private log search. There must be no matches; rotate a credential immediately if one is found.

## 5. Provider-project checks

In Google AI Studio/Cloud Console, verify each environment value belongs to its intended separate project, both APIs are enabled, and both projects can access the configured primary/fallback models. The bot does not rotate successful calls and makes no claim that two keys multiply quota.

## 6. Submission and recovery checks

An identical second submit returns the existing result and writes no duplicate attempts. A different answer array after completion returns `400` by the documented immutable policy. Production browser-supplied user IDs are ignored; only verified Telegram `initData` is trusted.

For a posting-failure drill, block Telegram temporarily, run a subject, restore Telegram, and use `--force-post`. Confirm no new Gemini generation log appears. At 20:30 IST, recovery skips `posted` and future subjects, reuses `generated`/`posting_failed` packs, and returns nonzero only if retryable failures remain unresolved.
