# Migrations

`001_init.sql` is the initial schema. `002_subject_quiz_runs.sql` adds the
subject-run lifecycle, chapter history, initial quiz submissions, and
recovery/leaderboard indexes. `003_repeat_quiz_attempts.sql` preserves those
rows while allowing intentional retakes with idempotent client attempt IDs.

New migrations use the Supabase CLI timestamp convention and live in
`supabase/migrations/`. The current sequence for every installation is:

1. `database/schema.sql` for a brand-new project, or legacy migrations
   `001` through `003` for an existing project that has not run them.
2. `supabase/migrations/20260718015054_atomic_quiz_integrity.sql`.
3. `supabase/migrations/20260718112044_question_provenance_reporting.sql`.

`database/schema.sql` is therefore the legacy bootstrap schema, not the final
post-migration state. This avoids duplicating the transactional function bodies
in two files that could drift apart.

Convention for future changes:

1. Run `supabase migration new <short_description>` and edit the timestamped
   file in `supabase/migrations/`.
2. Write it as `alter table ...` / `create table if not exists ...` — additive
   and idempotent, never a destructive rewrite of existing data.
3. Add migration, backfill, verification, and rollback notes under `docs/`.
4. Validate syntax locally, then apply the file through the Supabase migration
   workflow or SQL Editor only after a backup/checkpoint.

The application process does not run DDL. Supabase CLI or SQL Editor remains an
explicit operator step, which keeps web and bot startup safe and predictable.
