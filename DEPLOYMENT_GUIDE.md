# Deployment guide

Deploy in this order: database migrations, approved source import, server environment, FastAPI, bot
preflight, BotFather named-app URL, then one controlled subject run. Do not
deploy the new application before the atomic RPCs exist.

## 1. Apply the database migration

The current timestamped stack is:

```text
supabase/migrations/20260718015054_atomic_quiz_integrity.sql
supabase/migrations/20260718112044_question_provenance_reporting.sql
supabase/migrations/20260718160722_syllabus_v2_catalogue.sql
supabase/migrations/20260718171256_learning_resources_foundation.sql
supabase/migrations/20260718172756_learning_resources_fk_indexes.sql
```

For a new empty project, first apply `database/schema.sql`, then the timestamped
migrations in order. An existing project applies only its newer unapplied
migrations. The SQL is additive and rerunnable. The foundation backfills
historical question mappings and valid ten-position submissions while
preserving every legacy table/row.

Read `docs/MIGRATION_20260718.md` and
`docs/MIGRATION_20260718_PROVENANCE.md` before applying. Take a database backup or
project-branch checkpoint, run its preflight SQL, apply the canonical file with
the Supabase migration workflow or SQL Editor, and run its verification SQL.
Then rerun both Supabase advisors. Do not paste a database password or service
key into a migration file, issue, command transcript, or chat.

Expected intentional security posture: public tables have RLS and no browser
policies because only FastAPI/service-role access is supported. The migration
revokes `anon` and `authenticated`, makes legacy public views security-invoker,
and revokes direct browser execution of private functions.

The provenance migration seeds taxonomy but deliberately seeds no facts. Build
and manually review source bundles, then run:

```bash
python scripts/import_source_documents.py sources.json --dry-run
python scripts/import_source_documents.py sources.json --approve
```

After the learning-resource migration, an approved import also mirrors only
safe resource metadata (title, link, publisher, language/type defaults) from
the approved source rows. It never stores the source text or `fact_summary`.

Keep scheduled generation paused until every enabled chapter has at least one
approved, unexpired fact bundle. Missing sources fail closed; current affairs
require recent official/primary dated sources.

## 2. Configure GitHub Actions

Required Secrets:

```text
GEMINI_API_KEY_PRIMARY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_FORUM_TOPICS_JSON
SUPABASE_URL
SUPABASE_SERVICE_KEY
```

Recommended Secret:

```text
GEMINI_API_KEY_SECONDARY
```

Optional Secrets:

```text
TELEGRAM_GENERAL_THREAD_ID
TELEGRAM_ADMIN_CHAT_ID
TELEGRAM_ADMIN_USER_IDS
```

Repository Variables:

```text
TELEGRAM_BOT_USERNAME
MINIAPP_SHORT_NAME
QUESTION_VERIFICATION_MIN_CONFIDENCE=0.85
CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS=45
QUESTION_REPORT_THRESHOLD=3
```

No new credential or paid search API is required. `QUIZ_CLAIM_TIMEOUT_MINUTES`
and `GEMINI_FACTUAL_TEMPERATURE` are optional runtime variables; their defaults
are 20 and 0.3 respectively.

The scheduled workflow resolves its exact canonical subject from one Python
mapping and uses `date-subject` concurrency with cancellation disabled. Manual
examples:

```text
mode=preflight
mode=subject-quiz, subject=history
mode=subject-quiz, subject=history, force_post=true
mode=subject-quiz, subject=history, force_regenerate=true
mode=recover-missed-quizzes
```

Run `preflight` first. It uses no Gemini quota and posts no Telegram message.

## 3. Configure the FastAPI host

Use Python 3.12 and install the deterministic runtime lock:

```bash
pip install -r requirements.lock
uvicorn app:app --host 0.0.0.0 --port "$PORT"
```

Required server values:

```text
SUPABASE_URL
SUPABASE_SERVICE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_BOT_USERNAME
MINIAPP_SHORT_NAME
TELEGRAM_FORUM_TOPICS_JSON
```

The API itself does not call Gemini for public GETs or submissions, but using
the same environment as the scheduled bot also includes:

```text
GEMINI_API_KEY_PRIMARY
GEMINI_API_KEY_SECONDARY
GEMINI_MODEL_PRIMARY=gemini-2.5-flash-lite
GEMINI_MODEL_FALLBACK=gemini-2.5-flash
GEMINI_FAILOVER_ENABLED=true
GEMINI_FACTUAL_TEMPERATURE=0.3
QUESTION_VERIFICATION_MIN_CONFIDENCE=0.85
CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS=45
QUESTION_REPORT_THRESHOLD=3
QUIZ_CLAIM_TIMEOUT_MINUTES=20
APP_TIMEZONE=Asia/Kolkata
DEV_ALLOW_UNVERIFIED_TELEGRAM=false
```

Keep `DEV_ALLOW_UNVERIFIED_TELEGRAM=false` in every public environment. Set
`CORS_ALLOWED_ORIGINS` only when the frontend is intentionally hosted on a
different trusted origin; same-origin deployment needs no CORS list.

Check `GET /api/health`. It should show safe configured booleans,
`application_version=3.2.0`, and
`migration_version=20260718172756`; it never proves the database migration was
applied, so preflight remains mandatory.

## 4. Configure forum topics and BotFather

1. Give the bot permission to post in the forum group.
2. With `TELEGRAM_ADMIN_USER_IDS` configured, run
   `python scripts/discover_topic_ids.py`.
3. In each real forum topic, send `/topicid <canonical-key>`. Build the private
   13-key JSON mapping from the replies.
4. In BotFather send `/myapps`, select the app belonging to
   `TELEGRAM_BOT_USERNAME`, and select the exact short name in
   `MINIAPP_SHORT_NAME`.
5. Choose **Edit Web App URL** and enter the HTTPS FastAPI root. Updating only
   Main Mini App/Open App does not change named-app deep links.
6. Fully close Telegram's Mini App cache and reopen a quiz.

Server logs should show `GET /api/quiz/<quiz-id>` and, after submission,
`POST /api/quiz/<quiz-id>/submit`. If they are absent, Telegram is opening a
different named-app deployment.

## 5. Controlled production verification

1. Run `python bot.py --mode preflight`.
2. Run the CI commands locally or wait for the PR check: Ruff, mypy, pytest,
   migration contract, and public-data scan.
3. Run one due/manual subject: `python bot.py --mode subject-quiz --subject history`.
4. Verify the generated questions cite approved source rows, share the selected
   normalized micro-topic, and each have a passing `question_verifications` row.
5. Verify one `quiz_runs` row owns a non-expired lease while processing and
   ends `posted` with ten mappings in `quiz_questions`.
6. Confirm the Telegram post appears only once in the correct thread and opens
   the subject-scoped quiz ID.
7. Confirm live mode renders ten questions; submit with a new `attemptId`.
8. Open `📚 আগে প্রস্তুতি নিন`; confirm it shows only the quiz's unique
   micro-topics and cached verified resources. Confirm the browser makes only
   the FastAPI `/resources` request and no live YouTube/web search.
9. Verify one `quiz_attempts` row and exactly ten
   `quiz_attempt_answers` rows. Retry the identical request and confirm no new
   row; retake with a new ID and confirm a second parent attempt.
10. Submit one question report from the authenticated review card. Confirm it is
   bound to that attempt, a duplicate returns conflict, and unrelated users or
   attempts cannot report it. Test the quarantine threshold with test users.
11. Check quiz/global leaderboard pages and confirm response rows contain no
   Telegram IDs, first/last names, or non-opted-in usernames.
12. Stop the API temporarily and open an existing static pack. Confirm the UI
   labels read-only fallback and cannot submit or claim a score.
13. Run `python scripts/check_public_data.py`; it must pass.
14. Trigger two manual runs for the same date/subject close together. One may
   proceed; the other must report that another worker owns the active lease.
15. Run Supabase advisors again and investigate every error/warning. Expected
    RLS-without-policy information is documented in the migration guide.

For provider failover, use a disposable test environment rather than changing
production credentials. Confirm a key-specific failure switches providers and
a successful primary call does not call the secondary. Never log or search by
printing a real key.

## 6. Recovery and rollback

If Telegram posting fails after generation:

```bash
python bot.py --mode subject-quiz --subject history --force-post
```

This reuses the stored checksum-valid pack. If status is `posting_unknown`,
first inspect the target forum thread: the request may have reached Telegram
even though the worker lost the response. Automatic recovery deliberately will
not repost an ambiguous outcome. Use `--force-regenerate` only when content
itself is invalid and explicit replacement is intended. At 20:30 IST, recovery
skips future/posted subjects and takes over only an expired unambiguous lease.

For an application rollback, deploy the previous commit but retain the
additive database objects. Do not drop new attempt tables after they contain
data. A forward corrective migration is safer than destructive DDL. A full
database restore is the only complete rollback and loses every write after the
backup timestamp; see `docs/MIGRATION_20260718.md`.

## 7. Known deployment limits

- Static quiz files are still committed by each scheduled subject job, so the
  repository may receive up to 13 small fallback commits per day. Consolidated
  storage/commit batching belongs in a later operations phase.
- Source collection and learning-resource approval are operator imports in this
  phase; automated official-feed and YouTube discovery are not included.
- Post-migration advisor results cannot be known until an operator applies the
  migration; rerunning both advisors is a required deployment gate.
