# Deployment guide

Deploy in this order: local database tests, staging migrations, approved staging
source import, staging API, bot preflight, private Telegram lifecycle, production
approval, production migrations, Render, and one controlled production subject.
Do not deploy the new application before its exact database contract is ready.

The two hosted Supabase projects in scope are:

| Environment | Project | Project ref |
|---|---|---|
| Production | `telegram_group_data` | `tizxodkcpglmxgtwepor` |
| Staging | `telegram-quiz-bot-rollout-staging` | `prdrabmcivgbygzjnmko` |

Never modify `Citizen Affairs`. If staging is paused/inactive, stop the hosted
rollout until the owner resumes it; do not substitute production for staging.

## 1. Apply the database migration

The current timestamped stack is:

```text
supabase/migrations/20260718015054_atomic_quiz_integrity.sql
supabase/migrations/20260718112044_question_provenance_reporting.sql
supabase/migrations/20260718160722_syllabus_v2_catalogue.sql
supabase/migrations/20260718171256_learning_resources_foundation.sql
supabase/migrations/20260718172756_learning_resources_fk_indexes.sql
supabase/migrations/20260718174844_learning_resources_legacy_pack_compatibility.sql
supabase/migrations/20260718181849_personalized_learning_foundation.sql
supabase/migrations/20260718183203_personalized_learning_fk_compatibility.sql
supabase/migrations/20260718184505_remove_redundant_personal_review_unique.sql
supabase/migrations/20260718185905_learning_analytics_leaderboards.sql
supabase/migrations/20260718190639_personal_practice_answers.sql
supabase/migrations/20260718192154_canonical_subject_learning_projections.sql
supabase/migrations/20260718192558_canonical_subject_storage_compatibility.sql
supabase/migrations/20260718194113_resource_quality_operations.sql
supabase/migrations/20260718203218_dedupe_source_resource_cache.sql
supabase/migrations/20260718220112_production_integrity_contract_v2.sql
supabase/migrations/20260718222134_learning_and_leaderboard_contract_v2.sql
supabase/migrations/20260722120827_revision_reports_and_rankings.sql
supabase/migrations/20260724212939_durable_write_rate_limits.sql
```

For a new local/disposable empty database, first apply `database/schema.sql`,
then the timestamped migrations in order. `database/schema.sql` is bootstrap
input, not a hosted migration: never run it on staging or production because it
contains older function definitions. An existing hosted project applies only
newer unapplied migrations recorded in its Supabase ledger.

Read `docs/MIGRATION_20260718.md` and
`docs/MIGRATION_20260718_PROVENANCE.md` before applying. Also read
`docs/MIGRATION_20260718_PERSONALIZED_LEARNING.md` and
`docs/MIGRATION_20260719_LEARNER_ANALYTICS.md`. Resource operations verification
and rollback are in `docs/MIGRATION_20260719_RESOURCE_OPERATIONS.md`. Read
`docs/MIGRATION_20260722_PRODUCTION_CONTRACT.md` for the integrity migration
family and `docs/MIGRATION_20260724_DURABLE_RATE_LIMITS.md` for the current
durable-write migration. Take a database backup or project-branch checkpoint,
run preflight SQL, apply with the Supabase migration workflow, and run
verification SQL.
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

Create separate GitHub Environments named `staging` and `production`. Put each
environment's secrets only in its matching environment. Never copy a production
credential into `staging` merely to make a smoke run pass.

The dedicated `.github/workflows/staging-smoke.yml` workflow is
`workflow_dispatch` only, has read-only repository access, and accepts only
`preflight` or one explicitly selected subject quiz. It hard-fails unless the
Supabase host resolves to `prdrabmcivgbygzjnmko`, static JSON writes and the
Telegram development bypass are disabled, and every required staging value is
present. Force posting or regeneration is off by default and requires the exact
staging acknowledgement documented by the workflow input.

The scheduled workflows are bound to `production`, use commit-pinned actions,
and verify the public production project ref before accessing Supabase.

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
YOUTUBE_API_KEY
```

Repository Variables:

```text
TELEGRAM_BOT_USERNAME
MINIAPP_SHORT_NAME
QUESTION_VERIFICATION_MIN_CONFIDENCE=0.85
CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS=45
QUESTION_REPORT_THRESHOLD=3
```

No paid search API is required. `YOUTUBE_API_KEY` only enables bounded YouTube
candidate discovery; without it, link checks and the missing-resource queue
continue to run. Every discovered candidate requires administrator approval.
`QUIZ_CLAIM_TIMEOUT_MINUTES`
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
mode=export-static-fallbacks
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
EXPECTED_SUPABASE_PROJECT_REF
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

Set `EXPECTED_SUPABASE_PROJECT_REF=prdrabmcivgbygzjnmko` for manual staging and
`EXPECTED_SUPABASE_PROJECT_REF=tizxodkcpglmxgtwepor` for production. A mismatch
makes preflight and readiness fail without logging the URL or key.
For local Supabase only, set `EXPECTED_SUPABASE_PROJECT_REF=local`; that value
is accepted only when `SUPABASE_URL` uses `localhost`, `127.0.0.1`, or `::1`.

Keep `DEV_ALLOW_UNVERIFIED_TELEGRAM=false` in every public environment. Set
`CORS_ALLOWED_ORIGINS` only when the frontend is intentionally hosted on a
different trusted origin; same-origin deployment needs no CORS list.

The checked-in `render.yaml` defines the Python 3.12 free web service in
Singapore, installs `requirements.lock`, starts Uvicorn on `$PORT`, waits for CI
checks before auto-deploy, and uses `/health/ready`. Before applying the
Blueprint, run `render blueprints validate`, then fill every `sync: false`
value in the Render Dashboard. Do not add a Render database; Supabase remains
the datastore.

Check `GET /health/live`: it should return HTTP 200 even if dependencies are
down. Check `GET /health/ready`: it must return HTTP 200, application `7.0.0`,
migration `20260724212939`, contract `2.2.0`, and all checks true. `/api/health`
is a strict compatibility alias. A 503 is a release blocker, not a warning.

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

## 5. Controlled staging verification

1. Dispatch **Staging Quiz Smoke** with `operation=preflight`. Do not transfer
   staging secrets into a local shell or production workflow.
2. Run the CI commands locally or wait for the PR check: Ruff, mypy, pytest,
   migration contract, and public-data scan.
3. Confirm the environment project ref is staging, then dispatch
   `operation=subject-quiz` with one already-enabled, source-covered subject.
   Leave both force inputs false.
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
10. Verify each answer created/updated one private review schedule and that
    wrong, uncertain/slow, and repeated-correct paths use the documented
    intervals. Confirm private revision endpoints reject a missing or invalid
    `X-Telegram-Init-Data` header.
11. Save exam/subject preferences and question/resource bookmarks; verify only
    the same Telegram-authenticated user receives them.
12. Submit one question report from the authenticated review card. Confirm it is
   bound to that attempt, a duplicate returns conflict, and unrelated users or
   attempts cannot report it. Test the quarantine threshold with test users.
13. Check quiz/global leaderboard pages. Confirm the current user has an
    unmistakable `আপনি` row and private rank card, including outside the top
    ten, and that rows contain no Telegram IDs or non-opted-in usernames.
14. Submit a wrong answer in authenticated practice. Confirm no answer key was
    present before POST; after POST, confirm the review/source and next-review
    date appear. In explicit revision mode only, confirm wrong plays the enabled
    sound exactly once, correct is silent, sound-off persists, and a report is
    bound to that revision attempt. Confirm normal first-attempt quizzes are
    always silent.
15. Check every typed leaderboard family and a canonical subject filter such as
    `computer`; confirm bounded SQL pages, opt-out behavior, and documented
    tie-break metadata.
16. Stop the API temporarily and open an existing static pack. Confirm the UI
    labels read-only fallback and cannot submit or claim a score.
17. Run `python scripts/check_public_data.py --history`; it must pass.
18. Trigger two manual runs for the same date/subject close together. One may
    proceed; the other must report that another worker owns the active lease.
19. Run Supabase advisors again and investigate every error/warning. Expected
    RLS-without-policy information is documented in the migration guide.
20. Trigger the resource workflow in `link-check` mode. Confirm the link-check
    rows contain safe categories and that a transient failure does not increment
    `failure_count`. Use disposable data to verify the third hard failure marks
    a resource stale and queues a Bengali/Hindi replacement.
21. If `YOUTUBE_API_KEY` is configured, trigger discovery with a small limit.
    Confirm new videos are inactive `pending_review` rows, then test approve and
    reject through the authenticated administrator API.
22. Do not run recovery, announcement, bulk generation, or static fallback
    export from the staging workflow. Those modes are intentionally absent.

Record the staging quiz ID and pass/fail evidence without recording signed
Telegram data. Do not activate any chapter during this test. Use
`docs/STAGING_GUIDE.md` and `docs/TELEGRAM_SMOKE_TEST.md` as the evidence forms.

## 6. Production release

1. Require green CI and completed staging evidence from the previous section.
2. Pause production schedules and verify the production project name/ref.
3. Follow `docs/PRODUCTION_ROLLBACK.md`: record the ledger and preservation
   counts, take the approved backup/checkpoint, and apply only unapplied forward
   migrations. Never run the bootstrap schema.
4. Run the exact contract RPC, Supabase security/performance advisors, bot
   preflight, and production `/health/ready`.
5. Apply the merged `render.yaml` Blueprint or deploy the reviewed commit to the
   existing Render service. Fill production secrets only.
6. Test one real quiz with an authorized account: answer leakage, idempotent
   retry, result, current-user rank, personal dashboard, and revision sound.
7. Resume one controlled subject, verify one Telegram post, then resume the
   normal schedule. Do not activate unfinished chapters.

For provider failover, use a disposable test environment rather than changing
production credentials. Confirm a key-specific failure switches providers and
a successful primary call does not call the secondary. Never log or search by
printing a real key.

## 7. Recovery and rollback

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
backup timestamp; see `docs/PRODUCTION_ROLLBACK.md`.

## 8. Known deployment limits

- Static fallback export is batched after final recovery; a failure before that
  checkpoint can leave the latest pack available only through the live API
  until the export mode is rerun.
- YouTube discovery is quota-bounded and optional. It never auto-approves a
  result, and official/article source collection remains an operator import.
- Post-migration advisor results cannot be known until the migration is
  applied; rerunning security and performance advisors is a deployment gate.
- A paused hosted staging project cannot be migrated or readiness-tested. Resume
  it first; never use production as the substitute test target.
