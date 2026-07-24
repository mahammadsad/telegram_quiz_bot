# Staging release guide

This guide is the only supported path for a release-candidate quiz. Staging is
`telegram-quiz-bot-rollout-staging` with project ref
`prdrabmcivgbygzjnmko`; production is `telegram_group_data` with project ref
`tizxodkcpglmxgtwepor`. Never substitute one for the other and never touch
`Citizen Affairs`.

## Environment separation

GitHub Environment `staging` and the existing Render staging service must each
contain staging-only values for these names:

- `EXPECTED_SUPABASE_PROJECT_REF`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_FORUM_TOPICS_JSON`
- `TELEGRAM_GENERAL_THREAD_ID`
- `TELEGRAM_BOT_USERNAME`
- `MINIAPP_SHORT_NAME`
- `GEMINI_API_KEY_PRIMARY` and/or the configured fallback
- `DEV_ALLOW_UNVERIFIED_TELEGRAM`
- `WRITE_STATIC_QUIZ_JSON`
- `APP_TIMEZONE`

Verify names, presence, project ownership, and non-secret public identifiers;
never reveal values in screenshots, logs, pull-request text, or terminal output.
The required safe settings are the staging project ref,
`DEV_ALLOW_UNVERIFIED_TELEGRAM` false, `WRITE_STATIC_QUIZ_JSON` false, and
`APP_TIMEZONE` set to `Asia/Kolkata`.

## Order of operations

1. Require green PR CI, including PostgreSQL 17 migrations, security scans, and
   all four Playwright mobile projects.
2. Record staging preservation counts and the migration ledger.
3. Apply unapplied migrations in timestamp order. The expected final version is
   `20260724212939`; the contract remains `2.2.0`.
4. Deploy the exact CI-tested commit to the existing staging Render service.
   Keep its health probe on `/health/live` until a certified active quiz exists.
5. Check `/health/live` and the sanitized `/health/ready` body. Before quiz
   creation, only `activeQuizRetrieval` may fail.
6. Dispatch **Staging Quiz Smoke** with `operation=preflight`.
7. Choose one already-enabled chapter with current verified source coverage.
   Dispatch `operation=subject-quiz` once with both force inputs false.
8. Verify the database certification, answer-free public API, one private
   Telegram delivery, and complete learner lifecycle using
   `TELEGRAM_SMOKE_TEST.md`.
9. Retry the same safe operation and confirm it neither regenerates nor reposts.
10. Require `activeQuizRetrieval` true and `/health/ready` HTTP 200, then change
    the staging Render health path to `/health/ready`.
11. Preserve the certified active quiz. Remove only disposable test rows through
    an explicitly designed cleanup transaction that cannot match real users.

## Certified quiz evidence

Record identifiers and booleans, never answer content or signed Telegram data:

- selected enabled subject/chapter and source-document identifier;
- quiz ID and ordered mapping count exactly 10;
- immutable content-version count exactly 10;
- non-empty full content hashes count exactly 10;
- generated checksum and database read-back checksum equality;
- checksum contract version 2;
- `integrity_verified` true and state `ready` before posting;
- one Telegram message and correct forum topic;
- public pre-submission response contains no answer/explanation fields;
- a retry reuses the certified pack and does not post another message;
- `/health/ready` HTTP 200 after certification.

## Stop conditions

Stop without touching production if the project ref or URL differs, a required
staging value is absent, any answer appears before submission, a checksum
differs, a second Telegram post appears, an inactive chapter would need to be
enabled, or readiness has any failure other than the pre-certification active
quiz check. Repair on the branch, add a regression test, rerun CI, and restart
the staging gate from the affected step.
