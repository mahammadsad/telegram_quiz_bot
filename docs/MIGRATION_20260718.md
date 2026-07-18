# Atomic quiz integrity migration

Canonical file:
`supabase/migrations/20260718015054_atomic_quiz_integrity.sql`

## What it adds

- Expiring worker leases on `quiz_runs` and the atomic `claim_quiz_run` RPC.
- Ordered `quiz_questions` mappings, independent from simulated Telegram poll
  deliveries.
- Parent `quiz_attempts` and question-level `quiz_attempt_answers` history.
- Transactional quiz-pack and attempt-submission RPCs.
- Paginated SQL leaderboard RPCs with generated public aliases and opt-out
  fields; raw Telegram IDs are not returned.
- Server-only grants, RLS on public tables, invoker-safe public views, fixed
  function search paths, and browser-role revocation for private RPCs.
- Covering indexes for active leases, leaderboard reads, attempts, mappings,
  and the legacy foreign keys reported by the Supabase advisor.

The migration is additive and idempotent. Existing `polls` and
`quiz_submissions` remain intact, so the pre-migration application can still be
restored while no new-format-only writes have occurred.

## Backfill

The migration copies at most ten ordered question mappings for each existing
quiz run from historical `polls` rows. It then copies only valid ten-position
`quiz_submissions` whose quiz has ten unique ordered mappings into
`quiz_attempts` and expands them into question-level answers. Invalid answers,
out-of-range scores, duplicate-question packs, and incomplete legacy payloads
are left untouched for manual inspection; they are never silently invented or
deleted.

Before applying, take a Supabase database backup or create a project branch if
your plan supports it. Check that the expected legacy objects exist:

```sql
select to_regclass('public.questions') as questions,
       to_regclass('public.quiz_runs') as quiz_runs,
       to_regclass('public.quiz_submissions') as quiz_submissions;

select count(*) as invalid_legacy_submissions
from public.quiz_submissions
where jsonb_typeof(answers) <> 'array'
   or jsonb_array_length(answers) <> 10;
```

Apply the canonical migration once through the Supabase migration workflow or
paste that file into SQL Editor. It is safe to rerun after an interrupted
operator session.

## Verification

```sql
select quiz_id, count(*) as mapped_questions
from public.quiz_questions
group by quiz_id
having count(*) <> 10;

select attempt_id, count(*) as answer_rows
from public.quiz_attempt_answers
group by attempt_id
having count(*) <> 10;

select proname, prosecdef, proconfig
from pg_proc
join pg_namespace on pg_namespace.oid = pg_proc.pronamespace
where nspname = 'public'
  and proname in (
    'claim_quiz_run', 'save_quiz_pack_atomic',
    'submit_quiz_attempt_atomic', 'get_quiz_leaderboard_page',
    'get_global_leaderboard_page'
  );

select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated')
  and table_name in ('users', 'quiz_attempts', 'quiz_attempt_answers');
```

The first two queries should return no rows after the bot has only complete
packs/attempts. The grants query must return no rows. Run Supabase security and
performance advisors again after applying; the intentional "RLS enabled with
no policy" informational notices are expected because only `service_role`
access is supported in this phase.

Then deploy the application and run:

```bash
python bot.py --mode preflight
python scripts/check_public_data.py
```

## Rollback limitations

Do not drop the new tables after the new application has accepted attempts:
that would destroy question-level history. A safe application rollback is to
deploy the previous code while keeping the additive columns/tables/functions;
legacy tables were not removed. Revoke execution on the new RPCs if traffic
must be stopped. If a migration defect is found, prefer a forward corrective
migration.

Restoring a database backup is the only complete rollback after new-format
writes. It also discards all activity after the backup timestamp, so it should
be reserved for a verified data-integrity incident.
