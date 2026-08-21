# Production release and rollback

This runbook is the production gate for application version `8.6.0`. Passing local unit tests is not production evidence.

## Ownership and required inputs

The release owner needs:

- administrative access to the canonical Render service and its production environment;
- migration access to the expected Supabase project `tizxodkcpglmxgtwepor`;
- Telegram BotFather/Mini App configuration access;
- a designated synthetic Telegram test account and fresh `initData` secret for the deployed-smoke environment;
- a verified database backup/restore point;
- an approved quiz ID containing ten posted, answer-free questions;
- the full release commit SHA.

Never print service keys, bot tokens or synthetic `initData` in logs.

## Preflight

1. Review the PR diff, migration SQL, dependency changes and security workflow output.
2. Require green `Tests`, `mobile-browser`, `Security`, disposable PostgreSQL migration tests, public-data history scan and secret scan.
3. Record the release commit:

   ```bash
   git rev-parse HEAD
   ```

4. Create and verify a production database backup/restore point. Record its identifier outside the repository.
5. Confirm production secrets and these non-secret values in Render:

   ```text
   APP_ENVIRONMENT=production
   PUBLIC_APP_URL=https://telegram-quiz-platform.onrender.com
   PUBLIC_API_BASE_URL=https://telegram-quiz-platform.onrender.com
   EXPECTED_SUPABASE_PROJECT_REF=tizxodkcpglmxgtwepor
   ```

6. Confirm the rollback owner is present and the previous known-good application commit is available.

## Database migration order

Apply exactly in this order using the repository's normal Supabase migration mechanism:

1. `supabase/migrations/20260820090000_server_timed_daily_attempts.sql`
2. `supabase/migrations/20260820100000_question_verification_independence.sql`
3. `supabase/migrations/20260820110000_learning_test_catalog.sql`
4. `supabase/migrations/20260820120000_privacy_rights.sql`

Run the disposable migration job first. After production application, verify the migration ledger and contract functions. These migrations are additive; do not manually reorder, partially paste or edit them in the database console.

Do **not** schedule or manually call `public.process_due_account_deletions` until legal retention scope, backup, restore and grace-period operations have separate written approval.

## Staging gate

1. Deploy the exact release commit to staging.
2. Verify `/version` reports `applicationVersion: 8.6.0`, the expected full `commitSha`, staging environment and build time.
3. Verify root HTML, CSS, JS, icon, manifest, service worker, `/health/live`, `/health/ready`, an answer-free quiz, server-timed start/submission and dashboard with only the synthetic user.
4. Test a duplicate submission with the same attempt ID; it must be idempotent.
5. Submit forged client duration telemetry; it must not become trusted ranking time.
6. Verify a quiz/test public response has `X-Answer-Free-Payload: 1`, an ETag and no answers. Verify personalized responses are `Cache-Control: no-store`.
7. Exercise application rollback to the prior image while leaving additive migrations in place, then redeploy the candidate and repeat readiness/smoke.

Do not continue if any gate is red.

## Production deployment

1. Deploy the exact staged commit through the repository's normal Render deployment integration.
2. Wait for Render health to pass; do not infer success from a build alone.
3. Run the `Canonical deployment smoke` workflow with the release SHA, approved quiz ID and authenticated input enabled. The production environment supplies `SMOKE_TELEGRAM_INIT_DATA`.
4. Independently inspect:

   ```text
   GET https://telegram-quiz-platform.onrender.com/version
   GET https://telegram-quiz-platform.onrender.com/health/live
   GET https://telegram-quiz-platform.onrender.com/health/ready
   ```

5. In BotFather/Telegram Mini Apps, set and then verify the launch URL is exactly the canonical HTTPS URL. Open it from Telegram with the synthetic account and repeat start, submit, dashboard, catalog, export request and deletion-request cancellation. Do not create a due deletion request for a real learner.
6. Check all 13 due subject jobs globally. Replay production dead letters only through the approved idempotent operator path, with reviewed content. Require 13/13 posted and a fallback for every posted quiz.
7. Record release SHA/version, smoke run, migration ledger, Telegram verification, 13/13 evidence and rollback owner in the release record.

## Rollback

Trigger rollback for readiness failure, authentication/submit regression, answer leakage, timing regression, migration contract mismatch, elevated errors, missing content or privacy-control failure.

1. Disable new traffic or put the service in maintenance mode if answer leakage, data integrity or privacy is at risk.
2. Roll the Render application back to the previous known-good image/commit.
3. Do **not** drop new tables, columns, functions or audit records. The migrations are designed to coexist with the prior application. Use a reviewed forward-fix migration if schema behavior must change.
4. Keep account-deletion processing disabled. Cancel only synthetic pending requests created during smoke.
5. Re-run previous-version live/ready and its supported smoke; verify scoring and answer-free public responses.
6. Preserve logs/evidence, classify the incident, and open a forward-fix PR. Do not replay content jobs until the failure class is understood.

## Post-release observation

For at least one full daily cycle, monitor readiness, submit errors, server-timing anomalies, model verification bases, source expiry, global subject outcomes, reserve depletion, cache headers and privacy endpoint errors. Production is restored only after real deployed evidence—not repository state—shows healthy authenticated flows and 13/13 delivery.
