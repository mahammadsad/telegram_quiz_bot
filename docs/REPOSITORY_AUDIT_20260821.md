# Repository audit — 2026-08-21

## Outcome

The repository already contains a strong competitive-exam foundation: verified
question generation, immutable content identity, deterministic validation,
durable scheduling, server-side scoring, negative marking, PYQ provenance,
timed multi-section mocks, spaced revision, personalized mastery, moderation,
privacy-safe rankings, PWA fallback behavior, and deployment runbooks.

The main product blocker found in the current tree was the Main Mini App entry
point. Opening `/` without a quiz-specific Telegram deep link produced a quiz-ID
error and left no way to discover the rest of the product. This audit replaces
that dead end with a Bengali preparation hub and a safe recent-quiz catalogue.

## Implemented in this audit

- Added `GET /api/quizzes/recent`, bounded to 52 rows and projected from only
  checksum-certified, successfully posted ten-question quizzes.
- Kept the catalogue answer-free and free of user or Telegram identifiers;
  malformed, legacy, duplicate, unknown-subject, and incomplete rows fail
  closed.
- Added a responsive root hub with recent quizzes and direct entry points for
  due revision, full mocks, and personal progress.
- Added useful empty, network-error, and retry states so core study routes remain
  reachable during a catalogue outage.
- Added the catalogue to the service worker's explicitly answer-free network-
  first cache and bumped the UI cache identity.
- Made the full-history public-data scanner work safely in workspaces whose Git
  ownership differs from the executing user, without changing global Git
  configuration.
- Added service, API, privacy/cache, source-contract, error-path, and real mobile
  browser coverage for the new behavior.
- Added covering indexes for both durable job-queue subject foreign keys.
- Moved `pg_trgm` from the API-exposed `public` schema to `extensions`, updated
  the fuzzy-search RPC atomically, and removed the verified duplicate staging
  trigram index.

## Verification

- Python: 457 passed, 32 skipped, 1 dependency deprecation warning.
- Browser: 88 passed across 320×568, 360×800, 390×844, and 412×915.
- Ruff: passed.
- Mypy: passed for 79 source files.
- Bandit high-severity scan: passed.
- Locked Python and npm dependency audits: no known vulnerabilities.
- Current-tree and complete Git-history answer/credential scan: passed.
- `git diff --check`: passed.

The 32 skipped Python cases require the disposable PostgreSQL test database
described in the README. The warning is emitted by FastAPI's compatibility
import for Starlette TestClient and does not affect runtime behavior.

## Hosted staging evidence

On 2026-08-21, the connected staging project was advanced through
`bound_cached_source_resource_titles`, `current_affairs_claim_hash_parity`,
`job_subject_fk_indexes`, and `harden_pg_trgm_extension`. Pre/post counts stayed
at 6 users, 69 questions, 10 quiz runs, and 435 source documents. Both new
contract versions are exact and ready, the fuzzy-search RPC remains callable,
and Supabase reports no security or performance warnings. The existing public
RLS-without-policy notices are informational deny-by-default controls.

After synchronizing the concurrent 8.6.0 production-readiness merge, staging
also received its four intervening tracked migrations: server-timed daily
attempts, independent question verification, the learning-test catalogue, and
privacy rights. The timing and verification contracts are exact and ready, the
catalogue/privacy RPCs exist with service-role-only grants, and all four
preservation counts above remain unchanged.

The exact 8.6.0 commit `be883b5eb30664b2b92dcf7df2fa35549d14c31c` was
deployed to the isolated Render staging service. After adding the two missing
same-origin public URL settings, `/health/live` and `/health/ready` both
returned HTTP 200 and every exposed readiness check was true. The guarded
GitHub staging preflight also passed.

The first guarded Computer quiz run exposed historical schema drift: the
`chapter_history` table lacked the unique subject/date constraint required by
`finalize_quiz_post`. Telegram had acknowledged message `2485`, so the
application correctly recorded `posting_unknown` and refused to retry. Staging
had no duplicate history rows. An additive migration restored uniqueness, a
strict stored-receipt recovery path was added, and the already-delivered
certified ten-question quiz was finalized without sending a second message.

GitHub Tests run 348 and Security run 16 passed on the published fix commit,
including the disposable PostgreSQL build, all migrations, PostgreSQL-backed
behavior, mobile browser tests, dependency review, Bandit, dependency audits,
and Python/JavaScript CodeQL.

## External release gates still requiring deployment access

These are not safely completable from a source-only workspace and must not be
represented as done until evidence exists:

- Publish and deploy the post-finalization drift repair, then reconfirm the
  updated exact commit remains HTTP 200-ready in staging.
- Exercise a complete answer-free quiz lifecycle in the real Telegram staging
  Mini App, including post, attempt retry, retake, report, bookmark, and revision.
- Review production project ownership, backup/rollback approval, deploy, and
  post-deploy health and critical-flow checks.
- The daily Telegram reminder preference remains deliberately disabled because
  a consented, deduplicated private-message delivery worker is not implemented;
  the UI accurately labels it as unavailable and always persists `false`.

The authoritative operational checklist remains
`docs/PRODUCTIONIZATION_CHECKLIST.md`.
