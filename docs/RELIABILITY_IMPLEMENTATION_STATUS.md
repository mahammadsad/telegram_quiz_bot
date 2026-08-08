# Reliability implementation status

Updated: 2026-08-08

Branch: `codex/phase-d-deterministic-verification`

Baseline commit: `e390751782f6c0acf066b54273da1ceb8c65e5e1`

## Current phase

Phase A is published in draft PR #26 and both GitHub Actions jobs are green.
Phase B durable scheduling is published in draft PR #27. Its complete GitHub
gate, hosted staging database gate, Render deployment, and fail-closed staging
preflight are green. Production remains unchanged.
Phase C is green on draft PR #28. Its additive identity, evidence, candidate
persistence, durable replenishment, inventory-first due-time path, GitHub CI,
Render deployment, and fail-closed staging smoke are green. Phase D deterministic
verification is in progress on a separate stacked branch. Production is unchanged.

## Implemented

- Diversified saved packs reconstruct and revalidate their persisted
  source-to-micro-topic ownership while retaining checksum, verification,
  integrity, count, and source-bundle checks.
- Subject and recovery success share one outcome contract. Due-but-unposted,
  non-retryable, claimed, source-not-ready, and unknown-delivery states fail.
- Migration `20260808063007_atomic_quiz_post_finalization.sql` adds persisted
  post intent, atomic/idempotent acknowledgement finalization, explicit unknown
  reconciliation, usage/history updates, a readiness contract, and restricted
  grants.
- Recovery emits machine-readable and human-readable daily health from
  `quiz_runs_repo.list_for_date`, including state, stage, category, attempt
  count, last-error time, and known message ID.
- `config/production.toml` is the versioned non-secret policy source. Render,
  scheduled generation, source workflows, preflight, and readiness use or
  enforce the same source/schema intent and expose only its version/hash.
- Migration `20260808071500_durable_quiz_jobs.sql` adds exactly 13 daily jobs,
  append-only events, atomic lease claims with `SKIP LOCKED`, bounded durable
  retries, dead letters, explicit unknown-delivery quarantine/reconciliation,
  and service-role-only database access.
- A 15-minute GitHub heartbeat now claims all due work from PostgreSQL. Subjects
  fail independently, expired safe stages are reclaimed, expired posting is
  quarantined, and the final daily completeness report is database-derived.
- Migration `20260808084950_fix_leaderboard_privacy_contract_invoker.sql`
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
