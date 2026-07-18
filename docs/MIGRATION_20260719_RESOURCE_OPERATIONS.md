# Resource quality operations migration

Apply `20260718194113_resource_quality_operations.sql` after
`20260718192558_canonical_subject_storage_compatibility.sql`.

## Purpose

The migration adds private resource feedback, append-only link-check history,
a Bengali/Hindi discovery queue, reviewed channel policy, administrator review
RPCs, and a bounded operational-status RPC. It does not publish candidates or
grant database access to the browser.

## Preflight

Verify the previous stack is present and take a project backup or staging
checkpoint:

```sql
select
  to_regclass('public.learning_resources') is not null as resources_ready,
  to_regclass('public.quiz_micro_topics') is not null as taxonomy_ready,
  to_regprocedure(
    'public.submit_quiz_attempt_atomic(text,uuid,text,jsonb,integer,jsonb,jsonb)'
  ) is not null as atomic_submission_ready;
```

All three values must be true. Apply the canonical timestamped migration once
through the Supabase migration workflow.

## Verification

```sql
select public.get_operational_status();

select relname, relrowsecurity
from pg_class
where oid in (
  'public.resource_feedback'::regclass,
  'public.resource_link_checks'::regclass,
  'public.resource_discovery_queue'::regclass,
  'public.resource_channel_policies'::regclass
)
order by relname;

select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name like 'resource_%'
  and grantee in ('anon', 'authenticated')
order by table_name, grantee, privilege_type;
```

`schemaReady` must be true, every `relrowsecurity` value must be true, and the
browser-role grant query must return no rows. Run both Supabase advisors after
application. RLS-without-policy informational findings are intentional because
FastAPI and scheduled workers use only the service role.

Use disposable staging rows to verify behavior:

1. Re-submit the same feedback type for one user/resource and confirm it updates
   one row rather than creating a duplicate.
2. Record a timeout and confirm `failure_count` does not increase.
3. Record three hard failures and confirm only the third marks the resource
   inactive/stale and queues a Bengali/Hindi replacement.
4. Save one discovery candidate and confirm it is inactive and
   `pending_review`.
5. Approve or reject through `review_resource_candidate`; never update the
   moderation fields from a browser client.

## Rollback

Prefer an application rollback that retains these additive objects. Older code
does not depend on them. If a forward correction is needed, add a new migration
instead of editing the applied file.

Dropping the tables destroys learner feedback, link history, policies, and
discovery state. Do that only as part of a full project restore from a known
checkpoint; a restore also loses every write after the checkpoint. Pausing the
`resource-quality` workflow is the safe operational rollback for link checking
or discovery while keeping the data intact.
