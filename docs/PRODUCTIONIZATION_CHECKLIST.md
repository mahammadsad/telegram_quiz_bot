# Productionization checklist

This checklist is the release gate for the Telegram quiz platform. A checked item
means that the implementation exists **and** the corresponding automated or
staging test has passed. Source-code inspection alone is not sufficient.

## Release safety rules

- [ ] Apply every new database migration to `telegram-quiz-bot-rollout-staging`
  before production.
- [ ] Never run test data, destructive DDL, or experimental generation against
  `telegram_group_data`.
- [ ] Never modify the unrelated `Citizen Affairs` project.
- [ ] Never commit, log, or send a service-role key, Telegram token, Gemini key,
  or signed Telegram `initData` value.
- [ ] Do not activate a subject or chapter until its verified source coverage and
  a complete staging quiz lifecycle have passed.
- [ ] Treat `database/schema.sql` as empty-database bootstrap input only; applied
  environments advance exclusively through additive migrations.

## Phase 1 — critical backend repair

- [x] Store immutable `stem_hash` and full `content_hash` values for questions.
- [x] Create a new version when answers, choices, explanation, provenance,
  classification, language, difficulty, or fact version changes.
- [x] Prevent immutable question content from being overwritten in place.
- [x] Save exactly ten ordered question versions per quiz.
- [x] Recalculate the quiz checksum from rows read back from PostgreSQL.
- [x] Publish only a quiz whose generated and persisted checksums match.
- [x] Preserve a failed integrity run for diagnosis without exposing private data.
- [x] Make client-generated UUID attempt IDs mandatory end to end.
- [x] Return the original result for an idempotent submission retry.
- [x] Enforce duplicate-submission protection in PostgreSQL under concurrency.
- [x] Replace scattered migration constants with one application contract version.
- [x] Verify exact table, column, function-signature, grant, and RLS contracts.
- [x] Add `/health/live` and strict `/health/ready` endpoints.
- [x] Align application and database question-verification thresholds.

## Phase 2 — tests, security, and operations

- [x] Apply bootstrap plus every migration to a disposable PostgreSQL instance in
  CI and run behavioural database tests.
- [x] Test question versions, checksum mismatch, concurrent generation,
  idempotent submissions, RPC grants, RLS, revision scheduling, reports,
  quarantine, rankings, and statistics against PostgreSQL.
- [x] Remove the blanket storage-layer mypy exclusion and type its public API.
- [x] Use a shorter Telegram authentication window for sensitive writes.
- [x] Rate-limit submission, revision, practice, bookmark, report, preference, and
  resource-feedback writes.
- [x] Add private/no-store cache headers and browser security headers.
- [x] Pin GitHub Actions, minimize permissions, add timeouts and concurrency
  controls, and validate environment ownership before production jobs.
- [x] Point Render liveness/readiness monitoring to the correct endpoint.

## Phase 3 — Bengali-first user experience

- [x] Highlight the signed-in user on quiz and overall leaderboards.
- [x] Show a dedicated “আপনার র‍্যাঙ্ক” card and the user's row outside the top ten.
- [x] Show an unmistakable personal identity card on the overall dashboard.
- [x] Explain deterministic quiz, weekly, and overall ranking rules.
- [x] Wire every static button/link and add loading, duplicate-click protection,
  inline retry errors, and useful empty-state actions to the implemented controls.
- [x] Preserve unsent quiz progress during refresh and back navigation.
- [x] Add explicit revision mode and play mistake feedback only after an incorrect
  revision answer.
- [x] Add persistent revision sound and vibration preferences plus a sound test.
- [ ] Verify mobile layout, touch targets, focus visibility, and keyboard use.
- [x] Review visible Bengali terminology and error messages; use “পুনরাবৃত্তি”
  consistently in learner-facing navigation.

## Phase 4 — learning system

- [x] Track first/last attempt, last revision, attempt and outcome counts,
  consecutive correct revisions, interval, ease, next due date, and learning state.
- [x] Reschedule wrong revisions sooner and grow intervals for correct revisions.
- [x] Show due, overdue, weak, and recently mastered counts plus subject-wise due
  counts and direct revision actions.
- [x] Complete bookmark removal/list, attempt-owned report, quarantine,
  weak-topic, and recommended-next-action flows.
- [x] Keep quiz, practice, and revision statistics explicitly separated.
- [x] Document every statistic and leaderboard tie-break rule.

## Phase 5 — controlled content rollout

- [ ] Import approved Computer Education expansion sources into staging.
- [ ] Generate and validate one ten-question quiz per candidate chapter.
- [ ] Compare generated, stored, and API-returned checksums.
- [ ] Test posting once in a private Telegram topic.
- [ ] Test first attempt, retry, retake, ranking, report, bookmark, and revision.
- [ ] Activate one chapter, observe one complete scheduled cycle, then proceed one
  chapter at a time.
- [ ] Repeat the same gate for every other subject. The five intentionally inactive
  Computer Education expansion chapters remain inactive until this gate passes.

## Final release evidence

- [x] Local Python suite: 205 passed, 13 skipped (database cases skip without
  `TEST_DATABASE_URL`); the 13 database cases passed separately against a fresh
  disposable PostgreSQL database.
- [x] Local Ruff, mypy (58 source files), JavaScript parse, and whitespace gates
  pass.
- [ ] Manually exercise every control and error path in Telegram staging.
- [x] Hosted staging is `ACTIVE_HEALTHY`; both missing forward migrations applied
  successfully, original row counts were preserved, and the service-only
  contract reports ready.
- [x] Rollback-only staging database lifecycle passed exact-ten checksum
  readback, UUID retry/retake, current-user leaderboard, revision scheduling,
  and revision-report checks without leaving test rows.

- [x] CI passes from a clean checkout: GitHub Actions Tests run #77 completed
  successfully with 218 tests against PostgreSQL 17, plus the public-data and
  migration-security gates.
- [x] Staging migration version `20260722120827` and contract `2.2.0` are exact;
  all ten contract failure arrays are empty.
- [ ] Staging `/health/ready` returns HTTP 200.
- [ ] Staging end-to-end quiz lifecycle passes without answer leakage.
- [ ] Screenshots cover small Android widths, dashboard identity, out-of-top-ten
  rank, revision feedback, loading, error, and empty states.
- [ ] Production environment ownership is reviewed before migration/deployment.
- [ ] A reversible production migration and rollback/recovery plan is approved.
- [ ] Production `/health/ready` and critical user flows are checked after deploy.
- [ ] Release notes, operator guide, database runbook, and non-programmer
  verification instructions are current.
