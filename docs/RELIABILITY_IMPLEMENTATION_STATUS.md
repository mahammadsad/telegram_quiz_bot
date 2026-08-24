# Reliability implementation status

Updated: 2026-08-08

Branch: `codex/phase-e-pyq-mocks`

Baseline commit: `e390751782f6c0acf066b54273da1ceb8c65e5e1`

## Current phase

Phase A is published in draft PR #26 and both GitHub Actions jobs are green.
Phase B durable scheduling is published in draft PR #27. Its complete GitHub
gate, hosted staging database gate, Render deployment, and fail-closed staging
preflight are green. Production remains unchanged.
Phase C is green on draft PR #28. Its additive identity, evidence, candidate
persistence, durable replenishment, inventory-first due-time path, GitHub CI,
Render deployment, and fail-closed staging smoke are green. Phase D deterministic
verification and its adversarial release gate are green on draft PR #29. The
Phase D current-affairs event/claim migration and public staging gate are green.
The expanded mathematics, reasoning, English, and Bengali validators are green
in staging. Phase E1 personal learning is green on PR #30, including CI,
Supabase staging, Render staging, and non-posting smoke #24. Phase E2 exam
configuration is green on PR #31, including CI, Supabase staging, Render
staging, and non-posting smoke #25. Phase E3 previous-year provenance and
generalized timed mocks are green on PR #32, including CI, Supabase staging,
Render staging, and non-posting smoke #26. Phase E4 question-quality
administration is the active checkpoint.
Production is unchanged.

## Implemented

- Diversified saved packs reconstruct and revalidate their persisted
  source-to-micro-topic ownership while retaining checksum, verification,
  integrity, count, and source-bundle checks.
- Subject and recovery success share one outcome contract. Due-but-unposted,
  non-retryable, claimed, source-not-ready, and unknown-delivery states fail.
- Migration `20260808140812_atomic_quiz_post_finalization.sql` adds persisted
  post intent, atomic/idempotent acknowledgement finalization, explicit unknown
  reconciliation, usage/history updates, a readiness contract, and restricted
  grants.
- Recovery emits machine-readable and human-readable daily health from
  `quiz_runs_repo.list_for_date`, including state, stage, category, attempt
  count, last-error time, and known message ID.
- `config/production.toml` is the versioned non-secret policy source. Render,
  scheduled generation, source workflows, preflight, and readiness use or
  enforce the same source/schema intent and expose only its version/hash.
- Migration `20260808140819_durable_quiz_jobs.sql` adds exactly 13 daily jobs,
  append-only events, atomic lease claims with `SKIP LOCKED`, bounded durable
  retries, dead letters, explicit unknown-delivery quarantine/reconciliation,
  and service-role-only database access.
- A 15-minute GitHub heartbeat now claims all due work from PostgreSQL. Subjects
  fail independently, expired safe stages are reclaimed, expired posting is
  quarantined, and the final daily completeness report is database-derived.
- Migration `20260808140823_fix_leaderboard_privacy_contract_invoker.sql`
  removes an internal migration-table dependency from the invoker-safe privacy
  readiness RPC, preserving service-role-only execution without granting access
  to Supabase's internal migration schema.
- Phase C migrations `20260808093610`, `20260808093621`, and `20260808094602`
  add stable knowledge-point/source-fact/variant identity, append-only
  verification and usage, durable 3–5 item replenishment batches, inventory-day
  reporting, soft rotation with recorded degradation, and server-only accepted
  candidate persistence.
- Due-time assembly now tries verified inventory first and uses Gemini only when
  a safe ten-question pack cannot be assembled. Correctness, source freshness,
  review-required state, and quarantine are never relaxed.
- Phase D adds a versioned deterministic proof contract. New inventory candidates
  must pass common Unicode, option-pattern, date/effective-period, source-evidence,
  unique-answer, and explanation-conclusion checks. Supported mathematics and
  reasoning families are solved from machine-readable inputs; unsupported or
  under-constrained items fail closed before the probabilistic verifier runs.
- Phase D current-affairs ingestion now separates event date from publication
  date, clusters same-event releases, extracts exact-span atomic claims, records
  corroborating evidence, routes correction-like content to review, and exposes
  configurable daily/weekly/monthly/six-month pools. Current-affairs grounding
  reads only the verified event/claim pool; legacy publication-age fallback is
  retained for rollback compatibility.
- Phase D subject validation now covers ten typed mathematics families and
  eight typed reasoning families. Solver-produced traces, option units, and
  rounding policies are checked independently. Typed English/Bengali forms
  require exact authoritative rule spans; uncertain Bengali and translation
  correctness fail into explicit human-review reasons.
- Phase E1 adds per-user, per-knowledge-point mastery; immutable variant
  history; alternate verified-variant revision; a transparent
  1/3/7/14/30/60-day interval policy; daily learner rollups; explicit
  skipped/net-score/response-time trends; weakest/strongest knowledge points;
  a 50/30/20 recommendation policy; and server-filtered, paginated mastery.
  The unwired Telegram reminder control is disabled and explicitly labelled
  as coming soon.
- Phase E2 adds versioned, effective-dated exam/stage/paper/section entities,
  syllabus weights down to knowledge points, shared test definitions and
  instances, automatic `daily_quick` mapping for all legacy and future daily
  quizzes, and attempt/answer links to test and section instances. Public
  catalogue/test RPCs omit answer keys; unreviewed exam/mock templates remain
  drafts rather than inventing official rules.
- Phase E3 separates verified actual PYQs from generated previous-year-style
  practice; records official source/checksum/licence/reviewer metadata; applies
  answer corrections only through an append-only superseding-version audit;
  and adds idempotent timed attempts, section state/transitions, autosave,
  mark-for-review, section marking, deadline autosubmit, first-attempt rank
  cohorts, and subject/topic/knowledge-point analysis. Existing daily quiz
  attempts and answers are mirrored with their identifiers preserved.
- Phase E4 retains every existing report reason and adds duplicate/translation
  reasons; counts only independent credible reporters; discounts configured
  risk profiles, shared abuse clusters, and report bursts; and immediately
  quarantines deterministic contradictions or authoritative corrections.
  A service-role-only review queue exposes full evidence to allow review,
  dismissal, confirmed quarantine, explicit supersession, and reinstatement.
  Every transition is append-only and records the reviewer, resolution,
  replacement version, and the declared historical-score policy.

## Local evidence

- Baseline before changes: 304 tests passed, 20 database tests deselected;
  Ruff, mypy (61 files), and compile checks passed.
- Current local checkpoint: 321 non-database tests passed; Ruff and mypy (64
  production files) passed. PostgreSQL and browser coverage ran in GitHub CI.
- The new migration also parsed successfully as 22 PostgreSQL statements.
- Phase A remote CI: quality/tests and mobile-browser jobs both passed.
- Phase B GitHub checkpoint: the disposable PostgreSQL migration build, 346
  tests including concurrent exclusive claims, static-source validation,
  security contract, and mobile-browser suite passed.
- Hosted staging: all three reliability migrations are recorded, their feature
  contracts report `ready=true` with no permission failures, a rollback-only
  13-job ensure/claim/event simulation passed, and the Security Advisor has zero
  errors (the one warning is the pre-existing `public.pg_trgm` extension).
- Render staging is live on Phase C application `7.3.0` at commit `b20fb87`.
  Final staging smoke run `31252232235` passed and explicitly required all three
  Phase C migration versions plus `contentIdentity` and `verifiedInventory`.
- Phase C local checkpoint: 347 non-database tests pass; Ruff and mypy (69
  production files) pass. Staging compiled all three Phase C migrations;
  identity hashes match Python and PostgreSQL exactly, all Phase C contracts
  report ready with no permission failures, historical 69 question mappings
  remain readable, and rollback-only candidate/job/bundle gates passed.
- Phase D local checkpoint: 359 tests pass and 25 hosted database tests are
  skipped locally; Ruff and mypy (70 production files) pass. Adversarial tests
  reject wrong answers, two correct options, explanation contradictions, stale
  facts, broken Bengali/terminology, invalid maths, inconsistent reasoning, and
  duplicate current-affairs knowledge points with stable reason codes.
- Phase D deterministic staging checkpoint: CI run `31252866510` passed both
  quality/tests and real mobile browser jobs at commit `7665c44`; Render deploy
  `dep-d9rgb1qfngtc73dag1l0` is live and staging smoke run `31253037556`
  passed with application `7.4.0` and ready Phase C contracts.
- Current-affairs staging checkpoint: CI run `31253796861`, Render deploy
  `dep-d9rgocqfngtc73dbanm0`, and staging smoke run `31254084758` are green on
  commit `8c76c49`. Application `7.5.0` reports ready with migration
  `20260808103500`, `currentAffairsEvents=true`, and no failure categories.
- Current subject-validator checkpoint: GitHub CI run `31254564452`, Render
  deploy `dep-d9rh30ijnfac73fmotj0`, and staging smoke run `31254897967` are
  green at application `7.6.0`.
- Phase E1 local checkpoint: 394 tests pass with 27 hosted database tests
  skipped locally; Ruff and mypy (70 production files) pass. The local browser
  suite could not run because the locked Playwright package download was
  corrupted; disposable PostgreSQL and browser CI are required before staging.
- Phase E1 final gate: CI run `31255846386`, Render deployment
  `dep-d9rhh3ajnfac73fnm91g`, and non-posting smoke run `31256140930` are green
  on commit `4e753a4`. The Phase E contract is ready in staging and a cleanup-safe
  alternate-variant mastery simulation passed.
- Phase E2 local checkpoint: 400 tests pass with 29 hosted database tests
  skipped locally; Ruff and mypy (73 production files) pass. Disposable
  PostgreSQL and browser CI remain required before the staging migration.
- Phase E2 final gate: CI run `31256975753`, Render deployment
  `dep-d9rhv6f10e5c7384kslg`, and non-posting smoke run `31257177980` are green
  on commit `fd34190`. The exam configuration contract is ready in staging,
  every historical attempt/answer link is exact, and the advisor check found
  no Phase E foreign-key index gaps.
- Phase E3 local checkpoint: 408 tests pass with 29 hosted database tests
  skipped locally; Ruff and mypy (74 production files) pass. Staging compiled
  the migration, mirrored 12/12 attempts and 120/120 answers, returned an
  answer-free two-question verified PYQ catalogue, preserved one UUID attempt
  across retry, enforced two section transitions and section-specific marks,
  produced the declared first-attempt rank cohort and topic analysis, and
  autosubmitted an expired attempt at the exact 300-second cutoff. A rollback-
  only correction chain accepted an explicit superseding question and blocked
  direct verified-answer tampering. All synthetic rows were removed and the
  Phase E3 contract remains ready with no permission failures or unindexed new
  foreign keys.
- Phase E3 final gate: CI run `31258330375`, Render deployment
  `dep-d9rifk0n74is73etipc0`, and non-posting smoke run `31258516067` are green
  on commit `d7cb628`. The staging exercises also verified exact deadline
  accounting and append-only PYQ correction protection.
- Phase E4 local checkpoint: 414 tests pass with 31 hosted database tests
  skipped locally; Ruff and mypy (76 production files) pass. The disposable
  PostgreSQL migration and mobile-browser jobs remain required before the
  staging database can be changed.

## Deployment prerequisites

1. Keep PRs #27 and #28 in draft until their stacked dependencies and review plan
   are explicit.
2. Preserve the successful staging evidence and rerun preflight after any code,
   migration, credential, or configuration change.
3. Before production, require a truthful 13-subject daily report and a reviewed
   rollback/mitigation plan. Do not merge or mutate production outside that gate.

## Remaining risks

- Telegram and PostgreSQL cannot provide mathematical exactly-once delivery
  across an ambiguous external timeout; `posting_unknown` deliberately blocks
  automatic resend and requires reconciliation.
- PostgreSQL and Playwright are unavailable locally; their passing evidence is
  from the repository's disposable GitHub CI environment.
- Production migration history, source inventory, and Telegram routing have not
  been mutated. Render and Supabase changes were confined to staging.
