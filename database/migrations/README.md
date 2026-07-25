# Migrations

`001_init.sql` is the initial schema. `002_subject_quiz_runs.sql` adds the
subject-run lifecycle, chapter history, initial quiz submissions, and
recovery/leaderboard indexes. `003_repeat_quiz_attempts.sql` preserves those
rows while allowing intentional retakes with idempotent client attempt IDs.

New migrations use the Supabase CLI timestamp convention and live in
`supabase/migrations/`. The sequence for every installation is:

1. `database/schema.sql` once for a brand-new disposable/local database, or legacy migrations
   `001` through `003` for an existing project that has not run them.
2. Every `supabase/migrations/*.sql` file in filename/timestamp order. The
   authoritative current endpoint is
   `20260724212939_durable_write_rate_limits.sql`; existing hosted projects
   apply only ledger entries they have not already applied.

`database/schema.sql` is therefore a bootstrap-only schema, not the final
post-migration state. Never rerun it on staging or production: historical
`CREATE OR REPLACE FUNCTION` statements can replace newer hardened behavior.
Existing hosted databases receive only new timestamped migrations recorded in
the migration ledger.

Convention for future changes:

1. Run `supabase migration new <short_description>` and edit the timestamped
   file in `supabase/migrations/`.
2. Write it as `alter table ...` / `create table if not exists ...` — additive
   and idempotent, never a destructive rewrite of existing data.
3. Add migration, backfill, verification, and rollback notes under `docs/`.
4. Validate syntax locally, then apply the file through the Supabase migration
   workflow only after a backup/checkpoint so migration history is recorded.

The application process does not run DDL. The Supabase migration workflow is an
explicit operator step, which keeps web and bot startup safe and predictable.
Pasting the current migration into SQL Editor alone is insufficient because it
does not create the required migration-ledger entry and readiness stays closed.
