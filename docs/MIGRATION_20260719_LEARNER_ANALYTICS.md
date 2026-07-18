# Learner analytics and authenticated practice migration

Apply these files after the personalized-learning foundation:

1. `20260718185905_learning_analytics_leaderboards.sql`
2. `20260718190639_personal_practice_answers.sql`
3. `20260718192154_canonical_subject_learning_projections.sql`
4. `20260718192558_canonical_subject_storage_compatibility.sql`

The changes are additive. They preserve quiz generation, Telegram posting,
historical attempts, the existing quiz/global leaderboards, and emergency
static packs. No new environment variable, browser database key, or paid
service is required.

## Behavior

- `personal_practice_answers` records authenticated wrong, due, bookmark, and
  weak-topic practice without exposing the table to browser roles.
- `submit_personal_practice_answer` validates the selection and source, scores
  against the private question row, advances the shared 1/3/7/14/30/60 review
  schedule, and returns review details only after the write succeeds.
- A later correct practice answer resolves an earlier wrong-question entry.
- The learner dashboard aggregates attempts and practice in PostgreSQL. It
  returns streaks, daily goal, accuracy, response time, mastery, retake
  improvement, subject/chapter/micro-topic/difficulty performance, and bounded
  30-day/weekly activity arrays.
- Typed leaderboards cover daily, weekly, monthly, subject accuracy,
  improvement, consistency, and revision completion. Minimum-attempt rules,
  privacy opt-out, generated aliases, pagination, and deterministic tie-breaks
  are enforced in SQL.
- Canonical projection wrappers accept subject keys such as `computer` on both
  current and legacy deployments, whether `questions.subject` stores the key
  or the older internal name.

## Security

Every new function is `SECURITY INVOKER`. Direct table and RPC execution is
revoked from `PUBLIC`, `anon`, and `authenticated`; only `service_role` receives
the required grants. RLS is enabled on `personal_practice_answers` with no
browser policy, which intentionally denies all browser access. FastAPI remains
the only client and verifies signed Telegram Mini App data before calling the
private RPCs.

The due, wrong, bookmark, and dashboard reads contain no correct answer. The
practice write returns the correct index, explanation, and source only in its
post-submission response. Public leaderboard rows contain no Telegram ID or
private name.

## Verification

Run in staging before production:

```sql
select
  (select relrowsecurity from pg_class
   where oid = 'public.personal_practice_answers'::regclass) as rls,
  has_table_privilege(
    'anon', 'public.personal_practice_answers', 'SELECT'
  ) as anon_table_select,
  has_function_privilege(
    'anon',
    'public.submit_personal_practice_answer(uuid,uuid,integer,text,numeric,boolean)',
    'EXECUTE'
  ) as anon_practice,
  has_function_privilege(
    'service_role',
    'public.submit_personal_practice_answer(uuid,uuid,integer,text,numeric,boolean)',
    'EXECUTE'
  ) as service_practice,
  has_function_privilege(
    'anon', 'public.get_leaderboard_page(text,text,integer,integer)', 'EXECUTE'
  ) as anon_leaderboard,
  has_function_privilege(
    'service_role',
    'public.get_leaderboard_page(text,text,integer,integer)',
    'EXECUTE'
  ) as service_leaderboard;
```

Expected: `rls=true`; anonymous table/RPC values are false; service RPC values
are true. Submit a disposable wrong practice answer, check wrong/due/bookmark
and dashboard projections, then submit a correct answer and confirm the wrong
item resolves. A subject leaderboard request using `computer` must return
`subjectKey=computer` and an array-valued bounded `rows` page. Delete the
disposable user and confirm its cascaded practice/schedule rows are gone.

Run both Supabase advisors after the behavior check. RLS-without-policy
information is intentional for server-only tables. Investigate every new
warning or error; this migration should add none. Unused-index information can
appear before production traffic has exercised the new query paths.

## Rollback

Deploy the previous application version while retaining the additive database
objects and learner data. Do not drop practice or review rows after production
writes begin. If practice scheduling causes an incident, disable the affected
API route at the application layer and ship a forward corrective migration.
A database restore is the only full rollback and loses writes after the backup
timestamp.
