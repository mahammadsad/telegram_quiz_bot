# Question provenance and reporting migration

Canonical file:
`supabase/migrations/20260718112044_question_provenance_reporting.sql`

This migration must be applied after
`20260718015054_atomic_quiz_integrity.sql`. It has not been applied to
production by this repository or application.

## What it adds

- Normalized `quiz_subjects` → `quiz_chapters` → `quiz_micro_topics` taxonomy.
- One conservative “core concepts” micro-topic for every existing chapter;
  operator imports can add more precise reusable micro-topics.
- Verified `source_documents` fact bundles with URL, title, domain, source kind,
  publication/access dates, fact version, expiry, and review state.
- Immutable verified facts: corrections use a new `fact_version`/source row so
  existing question provenance never changes underneath an answer.
- Question-level provenance fields plus append-only `question_verifications`
  and private `question_generation_audits` for accepted/rejected verifier output.
- Lifecycle states from draft/generated through reported/rejected/archived.
- Attempt-owned `question_reports`, nine report reasons, duplicate/rate limits,
  and automatic `under_review` quarantine at the configured credible-report
  threshold.
- Server-only, security-invoker grounding/save/report RPCs and RLS on every new
  public table.

Existing questions are deliberately left `unverified` and `review_required`.
They remain readable in already-posted quiz packs, but they are not eligible
for new scheduler reuse until regenerated and independently verified.

## Preflight and source preparation

Confirm the foundation migration and expected taxonomy source are present:

```sql
select to_regclass('public.questions') as questions,
       to_regclass('public.quiz_runs') as quiz_runs,
       to_regclass('public.quiz_attempt_answers') as quiz_attempt_answers;

select subject, topic, count(*)
from public.questions
group by subject, topic
order by subject, topic;
```

Apply the canonical migration through the normal Supabase migration workflow.
Do not start scheduled generation yet: the migration seeds taxonomy, not facts.
Prepare a JSON bundle based on `docs/source_bundle.example.json`, then validate
and import it:

```bash
python scripts/import_source_documents.py sources.json --dry-run
python scripts/import_source_documents.py sources.json --approve
```

`--approve` is an explicit operator attestation. Current-affairs rows require
an official/primary HTTPS source and publication date. The bot accepts only
verified rows with `review_required=false`, rejects expired facts, and applies
the configured current-affairs age window (45 days by default).

Generation fails closed when the selected chapter has no approved facts. Seed
at least one approved bundle for every chapter that can become due before
enabling the schedule. No search API or paid grounding service is required.

## Verification

```sql
select count(*) as subjects from public.quiz_subjects;       -- 13
select count(*) as chapters from public.quiz_chapters;       -- 91
select count(*) as micro_topics from public.quiz_micro_topics; -- at least 91

select c.subject_key, c.name
from public.quiz_chapters c
where not exists (
  select 1
  from public.quiz_micro_topics mt
  join public.source_documents s on s.micro_topic_id = mt.id
  where mt.chapter_id = c.id
    and s.verification_status = 'verified'
    and not s.review_required
    and (s.expires_at is null or s.expires_at >= now())
)
order by c.subject_key, c.display_order;

select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated')
  and table_name in (
    'quiz_subjects','quiz_chapters','quiz_micro_topics','source_documents',
    'question_verifications','question_generation_audits','question_reports'
  );
```

The missing-source query must return no rows for every chapter enabled in the
production schedule. The grants query must return no rows. Run both Supabase
security and performance advisors after applying, then run:

```bash
python bot.py --mode preflight
python scripts/check_public_data.py
```

In a controlled run, confirm ten active questions have
`verification_status='verified'`, non-null source/micro-topic IDs, verification
rows, and a matching checksum. Submit a report from the review UI and confirm
it is tied to the same user's completed attempt. Use test users to verify that
the threshold moves the question to `under_review` and removes it from reuse.

## Moderation and rollback

Operators review open reports directly in the protected database/admin tooling.
Resolve a question and its reports in one transaction, recording
`reviewed_at`, `reviewed_by`, and `resolution`; set the question back to
`active` only after source and answer verification, otherwise use `rejected` or
`archived`. Never expose these tables or the service-role key to the browser.

The schema change is additive. A safe application rollback keeps all new
objects and deploys the previous server while scheduled generation is paused.
Do not drop verification or report tables after they contain writes. Prefer a
forward corrective migration. A database restore is the only complete rollback
and discards all activity after the backup timestamp.
