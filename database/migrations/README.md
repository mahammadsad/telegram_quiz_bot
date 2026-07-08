# Migrations

`001_init.sql` is the initial schema — identical to `database/schema.sql` at
the time it was written. `database/schema.sql` always reflects the full
**current** schema (apply that one for a brand-new Supabase project); this
folder is the incremental history for projects that are already running.

Convention for future changes:

1. Add a new file: `002_<short_description>.sql` (e.g. `002_add_mock_test_sessions.sql`).
2. Write it as `alter table ...` / `create table if not exists ...` — additive
   and idempotent, never a destructive rewrite of existing data.
3. Also update `database/schema.sql` so it stays the single source of truth
   for "what does the schema look like today."
4. Run the new file in the Supabase SQL Editor against production.

No migration runner is wired up (no psycopg2/alembic dependency) to keep
the project on the free-tier, dependency-light footprint — for a bot that
runs twice a day, pasting SQL into the Supabase dashboard a few times a
year is simpler and safer than adding a migration framework.
