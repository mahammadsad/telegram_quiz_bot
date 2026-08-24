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
6. Deploy the same tested commit to production, then enable the two-cron
   workflow (`*/15 * * * *` heartbeat and `0 15 * * *` completeness).

## Rollback

Disable the new scheduled workflow first. Roll back application code while
leaving the additive tables and functions in place; older code does not depend
on them. Do not drop job history during an incident. Reconcile any
`posting_unknown` rows before allowing retries or returning to automated sends.

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
