# Telegram Subject Quiz Bot

A source-grounded Bengali Telegram Mini App for one daily 10-question quiz in each of 13
competitive-exam subjects. FastAPI serves answer-free quiz payloads, validates
Telegram Mini App authentication, submits attempts through transactional
Supabase functions, and returns private review data and privacy-safe
leaderboards. Every newly generated question cites an operator-verified fact
bundle, belongs to a normalized micro-topic, and passes a separate source-only
verification request before the atomic save can activate it.

The syllabus-v2 foundation preserves the 13 Telegram subjects while expanding
the curriculum to 162 subject-specific chapters and 648 curated micro-topics.
New coverage is source-gated and stays out of rotation until its verified bundle
passes staging. See [`docs/SYLLABUS_V2.md`](docs/SYLLABUS_V2.md) for catalogue,
activation, compatibility, and rollout details. The preparation screen reads
only cached, operator-approved learning-resource metadata for the exact quiz
micro-topics. Automated discovery, wrong-answer practice, mastery,
personalized revision, bookmarks, and exam preferences remain later phases.

## Architecture

| Component | Responsibility |
|---|---|
| `bot.py` | Claims a date/subject run, selects a chapter, generates/validates a pack, posts once, and recovers missed work |
| `app.py` | Public quiz reads and authenticated submission/leaderboard APIs |
| `services/` | Chapter rotation, source grounding, independent verification, Gemini failover, validation, and quiz-pack rules |
| `storage/` | Small Supabase repositories; atomic writes use RPCs |
| `supabase/migrations/` | Current timestamped PostgreSQL migrations and security grants |
| `index.html` | Telegram-theme-aware quiz UI with a clearly read-only static fallback |
| `dashboard.html` | Privacy-safe global leaderboard UI |
| `.github/workflows/` | Exact schedule mapping, per-target concurrency, CI, preflight, and recovery |

The browser never receives a Supabase service-role key. It talks only to
FastAPI. FastAPI verifies signed Telegram `initData`; the trusted server and bot
use the service role against RLS-protected tables and explicitly granted RPCs.

## Reliable data flow

1. A GitHub schedule is mapped to one canonical subject from
   `config/schedule.py`; server wall-clock guessing is not used.
2. The worker claims `YYYYMMDD-subject-key` with an expiring database lease.
   Another worker cannot generate or post the same logical run concurrently;
   stale leases can be recovered.
3. Chapter selection sorts history newest-first, avoids the immediately prior
   chapter, prefers unseen chapters, then uses the 3/7/14/30-day review windows.
4. The bot loads approved facts for one normalized micro-topic. It fails closed
   if the chapter has no current source bundle; current affairs additionally
   require a recent, dated official/primary source.
5. Gemini primary/fallback behavior is bounded and classified. Generated packs
   must contain exactly 3 easy, 5 medium, and 2 hard questions, with balanced
   correct-answer positions and strict subject/chapter ownership.
6. A separate source-only verifier checks the answer, options, explanation,
   ambiguity, currency, micro-topic, and difficulty. Any failed check or score
   below the threshold rejects the whole pack.
7. One RPC revalidates source/taxonomy ownership and saves all question rows,
   verification evidence, and ten ordered mappings transactionally.
   The public fallback is exported without answers or explanations.
8. Telegram is called only by the lease owner. Only a successful API response
   marks the run posted. An ambiguous network outcome becomes
   `posting_unknown` and is never auto-reposted; an operator verifies Telegram
   before deciding whether to use the saved pack.
9. A submission RPC validates ten mappings/answers, calculates the score on the
   server, writes the parent attempt and ten question-level rows atomically,
   and returns review, rank, personal best, and attempt number. Reusing a client
   `attemptId` is idempotent; a new ID is an intentional retake.
10. Before starting, the preparation screen lists unique quiz micro-topics and
    at most three cached, verified resources per language and topic. It never
    performs a live search or sends a database credential to the browser.
11. Review cards show the verified source and accept signed, attempt-owned
    question reports. Duplicate/rate-limited reports are rejected; credible
    reports automatically quarantine a question for moderation.
12. Leaderboards aggregate and paginate in PostgreSQL. Public rows contain a
   generated alias or opted-in display name, never a Telegram ID.

Static JSON is an emergency read-only fallback. When the live API is
unavailable, the Mini App disables submission and scoring, labels the state,
and offers retry/preview controls. Correct answers are never bundled into a
public fallback.

## Schedule

The canonical subjects run hourly from 07:00 through 19:00 IST in this order:
`computer`, `bengali`, `reasoning`, `mathematics`, `english`, `miscellaneous`,
`polity`, `geography`, `science`, `economics`, `history`, `environment`, and
`current-affairs`. Recovery runs at 20:30 IST. `general` is announcement-only.

The schedule and subject identities live in `config/schedule.py` and
`config/subjects.py`; the complete curriculum lives in
`config/syllabus_catalog.py`. Workflow concurrency uses the logical date and
subject, waits instead of cancelling an active run, and has no run-ID component.

## Configuration

Copy `.env.example`; do not commit the populated file.

Required server/GitHub secrets:

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `TELEGRAM_FORUM_TOPICS_JSON`
- `GEMINI_API_KEY_PRIMARY`

Recommended second-provider secret:

- `GEMINI_API_KEY_SECONDARY`

Repository variables (public identifiers, not secrets):

- `TELEGRAM_BOT_USERNAME`
- `MINIAPP_SHORT_NAME`

Optional server settings:

- `TELEGRAM_GENERAL_THREAD_ID`, `TELEGRAM_ADMIN_CHAT_ID`,
  `TELEGRAM_ADMIN_USER_IDS`
- `GEMINI_MODEL_PRIMARY`, `GEMINI_MODEL_FALLBACK`, failover/backoff settings,
  and `GEMINI_FACTUAL_TEMPERATURE` (capped at `0.4`)
- `QUIZ_CLAIM_TIMEOUT_MINUTES` (minimum 5; default 20)
- `QUESTION_VERIFICATION_MIN_CONFIDENCE` (default `0.85`)
- `CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS` (default/database maximum `45`)
- `QUESTION_REPORT_THRESHOLD` (minimum `2`; default `3`)
- `CORS_ALLOWED_ORIGINS`, `WRITE_STATIC_QUIZ_JSON`

Development-only:

- `DEV_ALLOW_UNVERIFIED_TELEGRAM=true` permits a local fake user. It must stay
  false in every public deployment.

No new credential or paid search API is introduced. The learning-resource
foundation stores metadata and links only; it performs no YouTube or web search
and requires no `YOUTUBE_API_KEY`.

## Supabase setup

For a new project, apply `database/schema.sql`, then every file in
`supabase/migrations/` in timestamp order. Existing projects apply only the
newer unapplied files. The current stack ends with
`20260718172756_learning_resources_fk_indexes.sql`. The application never
applies DDL during startup.

The migration is additive, rerunnable, backfills historical pack/attempt data,
and locks tables, legacy views, and private functions to the service role. Full
preflight, verification, security, backfill, and rollback notes are in
`docs/MIGRATION_20260718.md` and
`docs/MIGRATION_20260718_PROVENANCE.md`.

Before enabling scheduled generation, import approved source facts for every
due chapter:

```bash
python scripts/import_source_documents.py sources.json --dry-run
python scripts/import_source_documents.py sources.json --approve
```

An approved import also mirrors safe title/link/publisher metadata into
`learning_resources`. It does not copy `fact_summary` or publisher content.

After applying, run Supabase security and performance advisors, then:

```bash
python bot.py --mode preflight
```

## Telegram and BotFather setup

1. Add the bot to the forum-enabled Telegram group with permission to post.
2. Run `python scripts/discover_topic_ids.py`. In each subject thread, an
   allowed administrator sends `/topicid <canonical-key>`.
3. Combine the 13 numeric results into `TELEGRAM_FORUM_TOPICS_JSON`. Never put
   the private mapping in frontend code or documentation.
4. In BotFather, open `/myapps`, choose the app whose short name matches
   `MINIAPP_SHORT_NAME`, and set its Web App URL to the deployed FastAPI root.
   Changing only the bot's Main Mini App URL does not update named-app links.

Posted links use
`https://t.me/<TELEGRAM_BOT_USERNAME>/<MINIAPP_SHORT_NAME>?startapp=<quiz-id>`.

## Local development and tests

Python 3.12 is the supported runtime. Runtime and development dependency locks
are committed separately.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.lock
ruff check .
mypy
pytest -q
python scripts/check_public_data.py
```

Start the local API:

```bash
DEV_ALLOW_UNVERIFIED_TELEGRAM=true uvicorn app:app --reload
```

Useful endpoints:

- `GET /api/health`
- `GET /api/quiz/{quiz_id}`
- `GET /api/quiz/{quiz_id}/resources`
- `POST /api/quiz/{quiz_id}/submit`
- `POST /api/questions/{question_id}/report`
- `GET /api/quiz/{quiz_id}/leaderboard?limit=20&offset=0`
- `GET /api/leaderboard?limit=20&offset=0`

Example submission shape:

```json
{"initData":"<signed Telegram data>","attemptId":"<new UUID>","answers":[0,2,1,null,3,0,1,2,3,0]}
```

Do not paste real signed data, keys, tokens, or thread IDs into issues, tests,
logs, or chat.

## Operations and recovery

```bash
python bot.py --mode preflight
python bot.py --mode subject-quiz --subject history
python bot.py --mode subject-quiz --subject history --force-post
python bot.py --mode subject-quiz --subject history --force-regenerate
python bot.py --mode recover-missed-quizzes
python bot.py --mode announce
```

`--force-post` reuses a checksum-valid saved pack. For `posting_unknown`, first
verify that Telegram did not accept the original message. `--force-regenerate`
explicitly replaces the pack; the flags are mutually exclusive. Recovery skips
posted/future runs, takes over only expired leases, and reuses valid saved
content before generating.

The health endpoint returns safe booleans plus application/migration versions.
It never returns secret values. Structured logs contain provider labels,
categories, quiz IDs, and safe status codes, not credentials or raw Gemini
responses.

Deployment and production drills are in `DEPLOYMENT_GUIDE.md`.

## Privacy and accessibility

- Production submissions require server-verified Telegram Mini App auth.
- Direct browser access to attempts/users is denied; service credentials stay
  server-side.
- SQL leaderboards honor `leaderboard_visible` and `username_visible`; default
  output is a stable generated alias.
- The UI follows Telegram light/dark variables, has keyboard navigation,
  reduced-motion behavior, and mobile-sized controls.
- Static mode never pretends to score or save an attempt.

## Troubleshooting

- `preflight` fails before generation: apply the current migration and verify
  required secret presence and all 13 numeric forum routes.
- A run remains generating/posting: wait for the configured lease expiry, then
  use recovery; do not manually create a second logical quiz ID.
- Telegram opens an old page: edit the named Mini App in BotFather and fully
  close/reopen Telegram's cached Mini App.
- Static fallback appears: check FastAPI/Render logs and retry the live API;
  static mode is intentionally non-submitting.
- Submission returns 401: open through Telegram and check bot token/init-data
  age; never enable the development bypass in production.

## Next platform phases

The next phase can add operator-reviewed discovery and link checks to the
cached resource library, then expand verified source/resource coverage one
subject at a time. Deterministic math/reasoning solvers, moderation admin UI,
wrong-question practice, spaced review, preferences, mastery analytics, and
personalized revision can follow on the question-level attempt model.
