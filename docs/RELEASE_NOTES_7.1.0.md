# Release notes — 7.1.0 source-backed 13-subject rollout

Version 7.1.0 prepares the daily 07:00–19:00 IST schedule to publish one
ten-question quiz for each of the 13 canonical subjects, without enabling the
full 162-chapter catalogue.

## Included

- Seven established Computer chapters remain approved.
- Every other subject receives exactly two reviewed chapters.
- Static rollout imports are filtered to the exact allowlist: 110 reviewed
  source records across 29 non-current-affairs chapters.
- Current affairs uses only canonical official PIB releases. The refresh
  rejects off-host URLs, stale/future/incomplete pages, strips executable
  content, versions corrections by content hash, and requires both selected
  chapters before any write.
- Missing source coverage stops before Gemini, quiz-run creation, database
  writes, or Telegram.
- Source text is treated as untrusted data by both generation and independent
  verification prompts.
- Current-affairs dates use `Asia/Kolkata` consistently in Python and
  PostgreSQL.
- The existing primary/secondary Gemini pool remains bounded. A secondary key
  can take over a retryable primary failure; keys are never logged.
- Source import and refresh workflows use protected environments, exact
  Supabase project guards, read-only contract checks before writes, pinned
  actions, least privilege, and no Telegram or Gemini credentials.
- `SOURCE_BACKED_ROTATION_ENABLED` defaults to false. The scheduler cannot enter
  the reviewed multi-subject rotation until the staged rollout is complete.

## Not included

- No unreviewed chapter from the wider catalogue is activated.
- No force-post or force-regenerate action is introduced.
- No historical users, questions, attempts, answers, reports, rankings,
  review schedules, sources, or resources are deleted or rewritten.
- No answer, explanation, Telegram signed data, key, token, or recovery
  material is added to a public payload.

## Release gate

Follow `MIGRATION_20260728_SOURCE_ROLLOUT.md`. Staging must prove source
coverage, migration state, all 13 isolated subject runs without posting, and
one normal Telegram lifecycle before production activation. Production then
observes the next normal scheduled cycle; force flags remain forbidden.
