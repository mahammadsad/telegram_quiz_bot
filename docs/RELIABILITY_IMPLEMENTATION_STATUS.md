# Reliability implementation status

Updated: 2026-08-08

Branch: `codex/phase-a-reliability`

Baseline commit: `e390751782f6c0acf066b54273da1ceb8c65e5e1`

## Current phase

Phase A is implemented locally and its non-database checks are green. It is not
approved for merge or deployment yet because the upgrade/database integration
gate and a production-equivalent 13-subject run have not run in this workspace.
Phase B has not started.

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

## Local evidence

- Baseline before changes: 304 tests passed, 20 database tests deselected;
  Ruff, mypy (61 files), and compile checks passed.
- Current full post-change checkpoint: 315 tests passed and 22 PostgreSQL tests
  skipped because no local database is available; Ruff, mypy (62 files),
  compile, and static source validation (110 rows/29 chapters) passed.
- The new migration also parsed successfully as 22 PostgreSQL statements.

## Deployment prerequisites

1. Run the full PostgreSQL integration suite from the existing schema upgraded
   through migration `20260808063007`; prove idempotency and forced rollback.
2. Run the browser suite when its browser dependency is available.
3. Apply the migration to staging before deploying the application commit.
4. Require staging readiness, source coverage, saved-pack recovery, one
   acknowledged post, idempotent replay, and answer-free public payload checks.
5. Produce a truthful production-equivalent report covering all 13 due
   subjects. Do not merge or deploy until the Phase A gate is green.

## Remaining risks

- Telegram and PostgreSQL cannot provide mathematical exactly-once delivery
  across an ambiguous external timeout; `posting_unknown` deliberately blocks
  automatic resend and requires reconciliation.
- PostgreSQL and Playwright are unavailable in the current workspace, so those
  are environmental non-runs rather than passing evidence.
- Production migration history, current source inventory, Telegram routing,
  and real deployment configuration have not been mutated or verified here.
