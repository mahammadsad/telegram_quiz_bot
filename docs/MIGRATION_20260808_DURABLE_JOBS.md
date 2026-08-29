# Durable quiz jobs rollout

Migration: `20260808140819_durable_quiz_jobs.sql`

## Purpose

The database becomes the durable scheduler of record. GitHub Actions is only a
15-minute heartbeat: it ensures the 13 daily subject jobs, atomically claims all
due work, and records every transition. A failed subject cannot prevent other
due subjects from running.

## Safe rollout

1. Apply every migration to disposable PostgreSQL and run the full test suite.
2. Apply this migration to staging before deploying the matching application.
3. Confirm readiness reports `durableQuizJobs=true` and migration version
   `20260808071500`.
4. Simulate delayed start, two concurrent dispatchers, retry exhaustion, an
   expired generating lease, and an expired posting lease.
5. Confirm exactly 13 unique jobs, no duplicate claims, normal retry recovery,
   `posting_unknown` quarantine, and an append-only event history.
6. Deploy the same tested commit to production, then configure the Supabase
   Cron primary heartbeat (`4,19,34,49 * * * *`) and daily completeness gate
   (`11 15 * * *`). Keep GitHub Actions at `43 * * * *` and `26 15 * * *` only
   as a staggered recovery path because GitHub scheduled events have no
   delivery SLA.

## Rollback

Unschedule `citizen-affairs-primary-dispatch`,
`citizen-affairs-daily-completeness`, and
`citizen-affairs-scheduler-reconcile` first. Restore the hourly GitHub recovery
workflow to a 15-minute cadence if the database scheduler cannot be repaired
immediately. Roll back application code while leaving the additive tables and
functions in place; older code does not depend on them. Do not drop job or
dispatch-request history during an incident. Reconcile any `posting_unknown`
rows before allowing retries or returning to automated sends.

## Primary scheduler credential renewal

Production Vault stores `github_scheduler_token` and
`github_scheduler_token_expires_at`; staging must not store either secret or
run the production scheduler. The contract intentionally reports not-ready 48
hours before expiry. Rotate the fine-grained/classic token without logging it,
update both exact Vault secrets, then call
`private.configure_primary_scheduler()` and verify
`public.get_primary_scheduler_contract()` reports every readiness flag true.
Finally invoke one normal `dispatch-due-jobs` heartbeat, reconcile its HTTP
response, and require GitHub to return HTTP 204. Never place the token in a
migration, application environment, workflow log, or public schema.

`pg_net` extension ownership belongs to the `extensions` schema. Migration
`20260829094700_pg_net_extension_schema_hardening.sql` preserves the installed
version and refuses to recreate the non-relocatable extension while an audited
scheduler request or a pg_net HTTP request is queued. Do not move it back to
`public`; if that guard fails, reconcile the outstanding request and rerun the
same migration rather than bypassing the queue check.
Recreating pg_net also resets `net.http_request_queue_id_seq`; migration
`20260829152100_pg_net_request_sequence_continuity.sql` advances it to the
retained scheduler audit maximum without lowering a newer sequence. Verify the
first subsequent request receives a new ID and reconciles to GitHub HTTP 204.

## Operator queries

Daily completeness:

```sql
select subject_key, status, retry_count, last_error_category,
       blocking_reason, telegram_message_id
from public.quiz_jobs
where logical_date = current_date
order by due_at;
```

Unknown delivery queue:

```sql
select id, quiz_id, subject_key, last_error_at, blocking_reason
from public.quiz_jobs
where status = 'posting_unknown'
order by last_error_at;
```
