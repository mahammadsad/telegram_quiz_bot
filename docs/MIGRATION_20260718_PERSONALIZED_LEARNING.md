# Personalized learning migration

Apply these files after the learning-resource migrations:

1. `20260718181849_personalized_learning_foundation.sql`
2. `20260718183203_personalized_learning_fk_compatibility.sql`

The change is additive and preserves quiz generation, Telegram posting,
historical attempts, public leaderboards, and emergency static packs. It
extends the previously reserved review schedule, backfills existing
question-level attempts without overwriting an existing schedule, and adds
private preferences and bookmark tables.

## Behavior

An `AFTER INSERT` trigger on `quiz_attempt_answers` runs inside the same attempt
transaction:

- wrong or unanswered: review in 1 day and return to learning;
- correct but marked/over 45 seconds: review in 3 days;
- normal correct progression: 7, 14, 30, then 60 days;
- repeated normal correct answers can reach `mastered`;
- every update records correct/wrong counts, average response time, recent
  confidence, and a bounded mastery score.

The FastAPI server is the only client. New tables have RLS enabled with no
browser policies; `public`, `anon`, and `authenticated` have no table or RPC
access, while `service_role` receives explicit minimum grants. Private question
lists omit correct answers and explanations.

## Verification SQL

Run in a disposable branch or staging project first:

```sql
select relname, relrowsecurity
from pg_class
where oid in (
  'public.user_preferences'::regclass,
  'public.user_question_bookmarks'::regclass,
  'public.user_resource_bookmarks'::regclass
);

select
  has_table_privilege('anon', 'public.user_preferences', 'SELECT') as anon_select,
  has_function_privilege(
    'anon', 'public.get_user_learning_dashboard(uuid)', 'EXECUTE'
  ) as anon_rpc,
  has_function_privilege(
    'service_role', 'public.get_user_learning_dashboard(uuid)', 'EXECUTE'
  ) as service_rpc;

select tgname, tgenabled
from pg_trigger
where tgrelid = 'public.quiz_attempt_answers'::regclass
  and tgname = 'sync_personal_review_schedule_after_answer';
```

Expected: RLS is true, both anonymous checks are false, service execution is
true, and the trigger is enabled. Then submit a disposable attempt and confirm
exactly one schedule row per user/question. Confirm due/wrong RPC JSON contains
no `correctIndex`, `correct_option`, Telegram ID, or moderation metadata.

Run both Supabase advisors. RLS-without-policy information is intentional for
these server-only tables. Investigate every new warning or error.

## Rollback

Roll back the application by deploying the previous commit while retaining the
additive database objects. Do not drop private learning tables after learners
have created schedules, preferences, or bookmarks. Disable the answer trigger
only as an emergency forward migration if scheduling writes cause an incident;
re-enable it after correction. A database restore is the only full rollback and
loses every write after the backup timestamp.

No new environment variable, Supabase browser key, BotFather setting, or paid
service is required.
