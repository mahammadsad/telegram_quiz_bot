# Durable write-rate migration

Required migration: `20260724212939_durable_write_rate_limits.sql`

Database contract: `2.2.0`

Apply this forward migration only after
`20260722120827_revision_reports_and_rankings.sql`. Do not edit either applied
file and never run `database/schema.sql` on a hosted project.

## Purpose

Quiz submissions, reports, and practice/revision answers already enforce
durable PostgreSQL limits in their transactional RPCs. This migration adds the
same durable boundary to the four remaining critical write families:

| Scope | Limit | Window |
|---|---:|---:|
| Bookmark changes | 60 | 1 hour |
| Preference saves | 20 | 1 hour |
| Resource feedback | 20 | 1 hour |
| Administrative resource review | 60 | 1 hour |

The private `write_rate_limit_buckets` table has RLS enabled and no `anon` or
`authenticated` privileges. Only `service_role` may access the table or execute
`enforce_write_rate_limit`. Fixed-window updates are serialized by transaction
advisory locks, and buckets older than two days are removed opportunistically.
The in-process limiter remains a secondary defense against rapid duplicate
button presses; it is not the durable enforcement boundary.

## Staging gate

1. Confirm the target is
   `telegram-quiz-bot-rollout-staging` / `prdrabmcivgbygzjnmko`.
2. Record the migration ledger and preservation counts from
   `docs/PRODUCTION_ROLLBACK.md`.
3. Apply only `20260724212939_durable_write_rate_limits.sql`.
4. Call `get_application_schema_contract` as `service_role`. It must report:

   - `contract_version` = `2.2.0`;
   - `required_migration_version` = `20260724212939`;
   - `migration_applied` and `ready` both true;
   - every missing/permission/configuration array empty.

5. Confirm `anon` and `authenticated` cannot read or write the bucket table and
   cannot execute the limiter.
6. Run the database integration suite. It must accept calls through the limit,
   reject the next call, and return HTTP 429 through the API translation layer.
7. Recheck the preservation counts before deploying the application.

## Verification SQL

Run through a secure SQL interface that does not print connection credentials:

```sql
select public.get_application_schema_contract();

select
  relrowsecurity,
  has_table_privilege(
    'anon', 'public.write_rate_limit_buckets', 'SELECT,INSERT,UPDATE,DELETE'
  ) as anon_access,
  has_table_privilege(
    'authenticated', 'public.write_rate_limit_buckets',
    'SELECT,INSERT,UPDATE,DELETE'
  ) as authenticated_access,
  has_function_privilege(
    'anon',
    'public.enforce_write_rate_limit(text,text,integer,integer)',
    'EXECUTE'
  ) as anon_execute
from pg_catalog.pg_class
where oid = 'public.write_rate_limit_buckets'::regclass;
```

Expected values are RLS true and all three browser-role privilege checks false.

## Failure recovery

The migration creates one private table, one index, one service-only function,
and forward replacements for four existing RPCs. It does not delete or rewrite
learner, quiz, attempt, report, source, revision, leaderboard, or resource data.

If application behavior regresses, pause schedules and redeploy the previous
application commit while leaving these additive objects in place. If the SQL
itself is defective, ship a new timestamped corrective migration. Do not rename
back the contract function, drop the bucket table, or edit this migration after
it has been applied. Restore a database checkpoint only for unrecoverable data
damage and only after recording which post-checkpoint writes would be lost.
