# Release notes — 7.0.0 production integrity release

This release hardens question identity, quiz persistence, attempt submission,
database readiness, revision learning, and the Bengali Mini App experience.

## Highlights

- Immutable question versions now use a normalized stem hash and a full-content
  hash covering choices, answer, explanations, classification, source evidence,
  fact version, difficulty, and language.
- Quiz generation becomes ready only after PostgreSQL reads back the exact ten
  saved versions and reproduces the generated checksum.
- Quiz and revision submissions require client UUIDs and replay the original
  result on a network retry.
- A refreshed result URL can recover only the signed-in learner's completed
  attempt by quiz ID and client UUID; a retake removes that URL identity and
  creates a new UUID.
- Readiness is fail-closed and checks the exact migration, contract, RPC
  signatures, grants, RLS, provider configuration, database access, and an
  active checksum-certified quiz.
- The quiz leaderboard shows a private “আপনার র‍্যাঙ্ক” summary and an unmistakable
  “আপনি” row, including outside the top ten. Typed rankings exclude practice and
  retakes from competitive accuracy.
- The personal dashboard now starts with Telegram identity and plain Bengali
  progress, rank, streak, subject, and revision information.
- Subject, chapter, and 7/14/30-day filters now update the visible performance
  panels, while overall leaderboards use disabled-state-aware 20-row pagination.
- Practice/revision submission failures are shown inline and retry the frozen
  answer with the same UUID instead of using a blocking browser alert.
- Revision answers use explicit server mode. A wrong revision can play one
  moderate sound and optional vibration exactly once; normal first attempts and
  correct revisions never play it.
- Revision answers show visual correction, explanation, verified source, next
  schedule, and an attempt-owned report control.
- CI now builds a disposable PostgreSQL database, applies bootstrap plus every
  migration, and tests concurrency, idempotency, permissions, RLS, ranking,
  revision, reporting, and quarantine behavior.
- GitHub Actions are commit-pinned, time-bounded, least-privilege, and protected
  by a production Supabase project-ref check. Render uses a checked-in Blueprint
  and strict `/health/ready` probe.
- The readiness contract now checks ten failure categories, including schema
  `USAGE`, and the service role can execute required RPCs without granting those
  functions to `anon` or `authenticated`.

## Operator note

No new subject or Computer Education expansion chapter is activated by this
release. Apply and validate all new migrations in staging, complete a private
Telegram lifecycle, and approve the production checklist before deployment.
Hosted staging and production have not been declared ready by the local test run.

## UI description

The mobile dashboard uses high-contrast rounded cards, Bengali-first labels,
large touch targets, a Telegram avatar/initials identity panel, concise metric
tiles, an accessible progress chart, subject/chapter/time filters, current-user
leaderboard highlighting, and a fixed four-item mobile navigation bar. The
revision page has a single-question focus, large answer options, clear
wrong/correct colors, restrained feedback, verified-source access, inline
retry-safe submission, and persistent sound controls.

## Local verification recorded for this release

- Application suite: `205 passed, 13 skipped` (the skipped tests require
  `TEST_DATABASE_URL`).
- Fresh disposable PostgreSQL contract suite: `13 passed` after bootstrap and
  every migration, ending at `20260722120827`.
- Ruff: passed. Mypy: passed for 58 source files. JavaScript parse and
  `git diff --check`: passed.
- Manual 320/360/412 px screenshots, private Telegram staging, staging readiness,
  and production readiness remain release gates.
