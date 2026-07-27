# Production integrity contract migrations

Apply these forward migrations in timestamp order after
`20260718203218_dedupe_source_resource_cache.sql`:

1. `20260718220112_production_integrity_contract_v2.sql`
2. `20260718222134_learning_and_leaderboard_contract_v2.sql`
3. `20260722120827_revision_reports_and_rankings.sql`
4. `20260724212939_durable_write_rate_limits.sql`

The final required migration is `20260724212939`; the application database
contract is `2.2.0`. `database/contract.py` is the only application source for
these identifiers.

## What changes

- adds immutable stem and complete-content hashes plus question version numbers;
- prevents mutation of versioned question content and provenance;
- saves exactly ten question versions and certifies a checksum recalculated
  from rows read back inside the transaction;
- records integrity failures without making a quiz publishable;
- requires unique client UUIDs for quiz and personal-practice attempts;
- adds auditable spaced-repetition fields and explicit revision/practice mode;
- adds revision sound/vibration preferences and current-user ranking RPCs;
- allows an authenticated revision answer to own a question report;
- makes competitive accuracy rankings first-attempt-only;
- exposes one exact contract RPC that checks tables, columns, function
  signatures, RLS, grants, verification threshold, and migration ledger.
- adds a private RLS-protected write-rate bucket and service-role-only limiter
  for bookmarks, preferences, resource feedback, and administrative resource
  review; submission, report, and practice/revision writes retain their
  existing PostgreSQL-backed limits.

## Safe rollout

1. Pause scheduled quiz generation and resource maintenance.
2. Confirm the target project name and ref. Staging is
   `telegram-quiz-bot-rollout-staging` / `prdrabmcivgbygzjnmko`; production is
   `telegram_group_data` / `tizxodkcpglmxgtwepor`.
3. Take a recoverable database backup/checkpoint and record the current migration
   ledger. Never run `database/schema.sql` on a hosted project.
4. Apply each unapplied migration to staging only.
5. Run the schema-contract RPC as the service role. It must return `ready: true`,
   contract `2.2.0`, migration `20260724212939`, and ten empty failure arrays
   (tables, columns, indexes, triggers, functions, grants, function settings,
   schema access, RLS, and table permissions).
6. Run staging API, UI, private Telegram-topic, duplicate-attempt, revision,
   report, ranking, and readiness checks.
7. Leave the migration additive objects in place if the application must be
   rolled back. Diagnose and ship a new forward migration for a database defect.
8. Apply to production only after approval and repeat the same verification.

## Recovery plan

The migrations preserve existing quiz, question, attempt, review, report, and
preference rows. Application rollback is therefore the preferred immediate
recovery: redeploy the previous application commit while schedules remain
paused. Do not drop new columns/tables or rewrite old question versions after
users have written data. A database restore is the last resort and loses writes
after the backup timestamp.

If checksum certification fails, keep the run in `integrity_failed`; do not
post it. If Telegram delivery is ambiguous, keep `posting_unknown`, inspect the
target topic, and never automatically post a second copy.

The exact checkpoint, preservation-count, application rollback, and
migration-failure procedure is in `PRODUCTION_ROLLBACK.md`.
