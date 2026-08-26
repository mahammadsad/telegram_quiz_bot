# Productionization checklist

This checklist is the release gate for the Telegram quiz platform. A checked item
means that the implementation exists **and** the corresponding automated or
staging test has passed. Source-code inspection alone is not sufficient.

## Release safety rules

- [x] Apply every new database migration to `telegram-quiz-bot-rollout-staging`
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
- [x] Rate-limit submission, revision, practice, bookmark, report, preference,
  resource-feedback, and administrative-review writes in PostgreSQL. The
  disposable and hosted staging probes both accept through the limit and reject
  the next event; the staging probe removed its one exact test actor.
- [x] Add private/no-store cache headers and browser security headers.
- [x] Pin GitHub Actions, minimize permissions, add timeouts and concurrency
  controls, and validate environment ownership before production jobs.
- [x] Add a manual-only staging workflow that fails closed on the exact staging
  project and excludes production, recovery, announcement, bulk, and fallback
  modes.
- [x] Scan the complete reachable Git history and current tree for supported
  credential shapes, and recursively scan public JSON for answer fields.
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
- [x] Verify mobile layout, touch targets, focus visibility, keyboard use,
  reduced motion, bottom-navigation clearance, and Bengali wrapping with real
  Chromium at 320×568, 360×800, 390×844, and 412×915.
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

- [x] Import the reviewed allowlisted static expansion sources into staging;
  guarded rollout `32901984753` validated, imported, and read back every selected
  chapter without activating rotation-disabled chapters.
- [x] Generate and validate one ten-question quiz for a source-covered Computer
  chapter in staging.
- [x] Compare generated and persisted checksums for that certified pack.
- [x] Test posting once in a private Telegram topic; reconcile the acknowledged
  message without reposting after the history-uniqueness drift was repaired.
- [ ] Test first attempt, retry, retake, ranking, report, bookmark, and revision.
- [ ] Activate one chapter, observe one complete scheduled cycle, then proceed one
  chapter at a time.
- [ ] Repeat the same gate for every other subject. The five intentionally inactive
  Computer Education expansion chapters remain inactive until this gate passes.

## Final release evidence

- [x] Local Python suite: 628 passed and 37 expected database tests skipped;
  CI run `32981014135` passed all 670 tests against disposable PostgreSQL 17 at
  release `65b3b4e`, including blocked-job recovery and durable retry rotation.
- [x] Local Ruff, configured mypy (90 source files), full-history scanner,
  browser JavaScript execution, and whitespace gates pass.
- [x] Local Playwright suite: 140 passed across all four required Android
  viewports, including automated WCAG checks and screenshot evidence.
- [x] GitHub Actions run #84 uploaded
  `mobile-browser-evidence-1` (artifact `8610726968`, 19.3 MB), retained through
  2026-08-23.
- [ ] Manually exercise every control and error path in Telegram staging.
- [x] Hosted staging applied ledger entry `durable_write_rate_limits`; contract
  `2.2.0` requires `20260724212939`, all failure arrays are empty, and every
  recorded application-data count is unchanged.
- [x] Rollback-only staging database lifecycle passed exact-ten checksum
  readback, UUID retry/retake, current-user leaderboard, revision scheduling,
  and revision-report checks without leaving test rows.
- [x] Replenishment fairness migration passed the disposable PostgreSQL build,
  a rollback-only six-subject staging probe, production dry-run `32693707165`,
  deployment `32693756799`, and a rollback-only ten-claim production probe.

- [x] Final branch CI passes from a clean checkout: GitHub Actions Tests run #84
  completed 242 PostgreSQL-backed tests, 6 migration-security tests,
  full-history scanning, and 48 browser tests across four projects.
- [x] Fair-claim release `a6a42ee` passed Tests run `32693496205` (including
  every migration on disposable PostgreSQL and 140 mobile-browser checks) and
  Security run `32693496198`.
- [x] Current production release `6970fbe` passed Tests run `32692689055`,
  Security run `32692689022`, strict readiness and canonical answer-free smoke
  run `32692761154` on `https://telegram-quiz-bot-h7p1.onrender.com`.
- [x] Staging required migration `20260724212939` and contract `2.2.0` are exact;
  all contract failure arrays are empty.
- [x] Staging application 8.6.0 at exact commit `2bd1086b` returned HTTP 200 from
  `/health/ready` with every exposed readiness check true; the guarded
  preflight passed.
- [x] Staging contract drift was repaired with the exact tracked platform
  contract, the 1.0.0 contract readback reported every check true, and the
  exact tested release `a5225f4` passed guarded preflight `32922058082` after a
  bounded cold-start retry.
- [x] The guarded Computer subject lifecycle posted one certified ten-question
  quiz, reconciled its stored Telegram acknowledgement after schema drift was
  repaired, and a guarded retry returned `QUIZ_ALREADY_POSTED` without a
  duplicate message or chapter-history row.
- [x] The exact `e4815e4` staging release generated, independently verified and
  privately posted the ten-question English quiz in guarded run `32922619905`;
  an answer-free deployed smoke passed for `20260826-english`, and retry
  `32922722535` returned `QUIZ_ALREADY_POSTED` without regeneration or reposting.
- [x] Guarded staging run `32943314315` on release `34fce08` generated,
  independently verified, atomically persisted and privately posted the
  ten-question Computer quiz after the Gemini schema serving-state repair.
  Retry `32943501370` returned `QUIZ_ALREADY_POSTED` without generation or a
  second Telegram message. Both staging health endpoints returned HTTP 200.
- [x] Operator recovery migration `20260826080000` passed the full disposable
  PostgreSQL chain and 665-test suite in run `32944613381`, then reported a
  ready staging contract with `operator_recovery=true`, no permission failures,
  service-role-only execution, and no advisor warnings or errors.
- [x] The audited production recovery requeued only blocked Computer job
  `063fa7f5-8ea1-4410-8616-9eae42e1292f` after confirming that neither the
  durable job nor its run had a Telegram acknowledgement. Durable attempt 5 on
  release `31d2ded` posted `20260826-computer`, recorded Telegram message 2526,
  cleared its prior error state, and left the job terminally `posted`.
- [x] Latest-history retry rotation advanced Environment through distinct
  chapters without weakening collision validation; normal durable run
  `32983417931` posted `20260826-environment` as Telegram message 2532.
- [x] Staging end-to-end quiz lifecycle passes without answer leakage. Release
  `36daa07` is live on both Render services; the staging answer-free smoke for
  `20260826-computer` and canonical production smoke run `32979274884` passed.
- [x] Screenshots cover all four Android widths, dashboard identity,
  out-of-top-ten rank, revision feedback, loading, retry/error, and empty
  states. The focused 2026-08-26 Playwright evidence run passed all 56 tests.
- [ ] Production environment ownership is reviewed before migration/deployment.
- [ ] A reversible production migration and rollback/recovery plan is approved.
- [x] Production `/health/ready` and answer-free critical public flows passed the
  fail-closed deployed smoke on 2026-08-26 at exact release `65b3b4e` in run
  `32981828237`; Tests run `32981014135` and Security run `32981014299` passed.
- [x] Release notes, staging/Telegram/mobile guides, database runbook, production
  rollback guide, and non-programmer verification instructions describe the
  current gates without claiming pending hosted results.
