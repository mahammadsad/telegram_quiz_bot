# Productionization implementation report

Status date: 2026-07-23

Feature branch: `agent/productionize-quiz-platform`

Required database migration: `20260722120827`

Application/database contract: `2.2.0`

This report records implemented and tested local work. It does **not** certify
hosted staging or production. Production was not queried or modified.

## Original problems confirmed

- Question reuse could depend on normalized question text even when options,
  answer, explanation, provenance, classification, language, or fact version
  changed.
- Generated checksums were not proven against the exact rows read back from the
  database before publication.
- Migration-version references and database-contract checks were distributed and
  incomplete; function signatures, grants, schema usage, RLS, and trigger/index
  contracts were not checked together.
- Health behavior could report success without proving that the application was
  ready to serve a real quiz.
- Empty or server-created attempt identities allowed submission retries to risk
  creating duplicate attempts.
- Result refresh had no ownership-scoped recovery route.
- Current-user identity and rank were difficult to find outside the visible top
  rows.
- Revision mode, sound, scheduling, reporting, bookmark, weak-topic, and
  recommendation flows were incomplete or insufficiently explicit.
- Several controls lacked complete loading, retry, empty, filtering, or paging
  behavior, and learner-facing terminology mixed Bengali and English.
- CI database tests inspected SQL text more often than exercising a real
  PostgreSQL contract, while workflow permissions and deployment ownership
  checks needed hardening.

## Implemented changes

- Immutable `stem_hash` and full `content_hash` question versions, protected
  historical content, and deterministic full-content hashing.
- Atomic ten-question persistence, saved-row readback, checksum recalculation,
  ready-state gating, failed-run preservation, and duplicate-generation locks.
- Mandatory UUID attempt identities, database uniqueness, concurrent retry
  idempotency, frozen-answer retry, double-click prevention, and refresh-safe
  owned-result recovery.
- One authoritative migration/schema contract with exact migration, tables,
  columns, indexes, triggers, function signatures/configuration, RPC grants,
  schema usage, table permissions, RLS, and verification-threshold checks.
- Separate `/health/live` and fail-closed `/health/ready` endpoints plus sanitized
  logging and private/security response headers.
- Server-only scoring, shortened write-auth validity, ownership checks, bounded
  rate limits, safe links, and no correct-answer data before submission.
- Current-user leaderboard highlighting, avatar/initial fallbacks, out-of-page
  current rows, a complete “আপনার র‍্যাঙ্ক” summary, deterministic ranking help,
  and 20-row overall leaderboard pagination.
- Bengali-first personal/quiz dashboards, subject/chapter/time filters, recent
  quizzes, learning recommendations, useful loading/error/empty states, and
  consistent “পুনরাবৃত্তি” terminology.
- Explicit revision/practice mode, wrong-revision-only sound/vibration, persisted
  controls, visual answer correction, source/explanation access, attempt-owned
  reports, and idempotent review scheduling.
- Spaced repetition with attempt/outcome history, consecutive revisions,
  interval/ease, due/overdue, weak/learning/mastered states, and subject counts.
- Commit-pinned GitHub Actions, least-privilege permissions, timeouts,
  concurrency protection, disposable PostgreSQL CI, project-ref ownership
  checks, and a Render Blueprint using strict readiness.

## Files changed

Configuration and operations:

- `.env.example`, `.python-version`, `pyproject.toml`, `pytest.ini`
- `.github/workflows/ci.yml`, `.github/workflows/main.yml`,
  `.github/workflows/resource-quality.yml`
- `render.yaml`, `scripts/apply_test_database.py`

Application and domain:

- `app.py`, `bot.py`, `config/settings.py`
- `models/question.py`, `models/user.py`
- `services/personal_learning_service.py`, `services/question_validation.py`,
  `services/quiz_pack_service.py`, `services/rate_limit.py`,
  `services/readiness_service.py`
- `utils/hashing.py`

Storage and database contract:

- `database/contract.py`, `database/schema.sql`,
  `database/migrations/README.md`
- `storage/contracts.py`, `storage/schema_contract_repo.py`
- `storage/attempts_repo.py`, `storage/bot_state_repo.py`,
  `storage/chapter_history_repo.py`, `storage/learning_resources_repo.py`,
  `storage/personal_learning_repo.py`, `storage/polls_repo.py`,
  `storage/question_reports_repo.py`, `storage/questions_repo.py`,
  `storage/quiz_attempts_repo.py`, `storage/quiz_packs_repo.py`,
  `storage/quiz_runs_repo.py`, `storage/resource_quality_repo.py`,
  `storage/source_documents_repo.py`, `storage/stats_repo.py`,
  `storage/submissions_repo.py`, `storage/users_repo.py`, and
  `storage/verification_audits_repo.py`

Frontend:

- `index.html`, `dashboard.html`, `practice.html`

Tests and dependency locks:

- `requirements-dev.txt`, `requirements-dev.lock`, `tests/conftest.py`
- `tests/test_api_submission.py`, `tests/test_bot_lifecycle_recovery.py`,
  `tests/test_chapter_and_leaderboard.py`,
  `tests/test_frontend_learning_cycle.py`, `tests/test_personal_learning.py`,
  `tests/test_question_validation.py`, `tests/test_quiz_pack_service.py`,
  `tests/test_deployment_contracts.py`, and `tests/integration/`

Documentation:

- `README.md`, `DEPLOYMENT_GUIDE.md`
- `docs/BUTTON_INVENTORY.md`, `docs/MIGRATION_20260722_PRODUCTION_CONTRACT.md`,
  `docs/NON_PROGRAMMER_VERIFICATION.md`,
  `docs/PRODUCTIONIZATION_CHECKLIST.md`, `docs/RELEASE_NOTES_7.0.0.md`, and
  `docs/STATISTICS_AND_RANKING_RULES.md`

## New forward migrations

1. `20260718220112_production_integrity_contract_v2.sql`
2. `20260718222134_learning_and_leaderboard_contract_v2.sql`
3. `20260722120827_revision_reports_and_rankings.sql`

These are additive/corrective migrations. Do not edit already applied historical
migrations, and never run `database/schema.sql` on an existing hosted project.

## Test evidence

- Full Python suite: **205 passed, 13 skipped, 1 warning**. The 13 skips are the
  expected database-integration cases when `TEST_DATABASE_URL` is absent.
- GitHub Actions clean checkout (Tests run **#77**): **218 passed, 1 warning**
  with PostgreSQL 17; the disposable database reported contract `2.2.0` and
  migration `20260722120827` before the suite ran.
- Fresh disposable PostgreSQL 17: bootstrap plus every migration applied, exact
  `20260722120827` ledger verified, all ten contract failure arrays empty, and
  **13 database-integration tests passed**.
- Ruff: **passed**.
- Mypy: **passed, no issues in 58 source files**.
- Frontend JavaScript parse (`index.html`, `dashboard.html`, `practice.html`):
  **passed**.
- Public-data/secret-name and answer-key scan: **passed**.
- Migration security contract: **6 passed** in the clean CI run.
- `git diff --check`: **passed**.
- GitHub issue audit: no open issues and no open pull requests were returned.

The single warning is Starlette's deprecation notice for its current TestClient
adapter. It does not fail a test, but should be resolved during a future pinned
dependency upgrade.

## UI result description

The dashboard now uses compact high-contrast cards, a prominent Telegram
identity panel, clear Bengali metrics, avatar/initial fallbacks, accessible
progress bars, subject/chapter/7–14–30-day filters, current-user ranking
highlighting, and disabled-state-aware paging. The quiz result can be restored
after refresh for the same authenticated user. Revision presents one large
question at a time, freezes a submitted answer, shows wrong/correct choices,
explanation and verified source, plays restrained mistake feedback only for an
incorrect revision, and shows retry errors inline.

Screenshots at 320, 360, and 412 px are still required against the private
staging URL. The available cloud-browser runner could not reach the local
workspace loopback server, so no manual screenshot is claimed.

## Hosted staging status

After the unrelated project was removed by its owner, Supabase restored
`telegram-quiz-bot-rollout-staging` (`prdrabmcivgbygzjnmko`) to
**ACTIVE_HEALTHY** on 2026-07-23. The restored ledger ended at contract `2.0.0`
and migration `20260718220112`; the two missing tracked forward migrations were
then applied in order:

1. `20260718222134_learning_and_leaderboard_contract_v2.sql`
2. `20260722120827_revision_reports_and_rankings.sql`

The restored staging backup contained earlier rollout/reset ledger entries.
During restoration, an early probe temporarily appeared empty and three legacy
idempotent setup entries were recorded. Once the backup was fully hydrated, a
narrow staging repair restored the verified-source similarity helper, the
hardened quiz status constraint, and invoker-safe server-only views. No table was
deleted, and before/after application row counts remained 3 users, 39 questions,
4 quiz runs, 4 legacy submissions, and 7 quiz attempts.

The hosted contract now reports **ready**, contract `2.2.0`, required migration
`20260722120827`, threshold `0.85`, and empty missing-table, column, index,
trigger, function, configuration, schema-permission, RLS, and table-permission
failure arrays. `service_role` can run the contract; `anon` and `authenticated`
receive PostgreSQL `42501`.

A rollback-only modern lifecycle created ten immutable verified question
versions, saved and read back an exact checksum, retried one UUID attempt
idempotently, created a genuine retake, highlighted the current leaderboard
user, tested a wrong revision and retry, verified intervals
`1/3/7/14/30/60`, and accepted a revision report. The transaction rolled back
fully, and the original staging row counts were rechecked unchanged.

Supabase advisors reported no errors. The remaining warnings are the historical
`pg_trgm` extension location in `public` and one duplicate trigram index in this
staging ledger. RLS-without-policy notices are expected deny-by-default behavior
for the server-only architecture; unused-index notices are expected on the
low-traffic staging project.

Production `telegram_group_data` was not queried or modified.

## Remaining release gates

- Deploy the application with staging-only credentials and verify
  `/health/ready` returns HTTP 200.
- Complete the private Telegram lifecycle, manual controls, retry/refresh,
  ranking, revision-sound, and 320/360/412 px checks.
- Keep all five Computer Education expansion chapters and every other unverified
  chapter inactive.
- Review the forward recovery plan, take the approved production backup, and
  deploy only after staging evidence is complete.
- Verify production project ownership, readiness, one controlled quiz, and one
  Telegram post before restoring schedules.
- Keep draft pull request #14 unmerged until all hosted application gates pass.

## Non-programmer verification

Follow `docs/NON_PROGRAMMER_VERIFICATION.md` from top to bottom. Stop immediately
if readiness is not HTTP 200, a checksum differs, an answer appears before
submission, a retry creates another attempt, a quiz posts twice, the “আপনি” row
is missing, or normal quiz answers play a mistake sound.
