# Atomic post-finalization migration — 20260808063007

Migration: `supabase/migrations/20260808140812_atomic_quiz_post_finalization.sql`

## Purpose

This additive migration makes a positively acknowledged Telegram post and its
usage/history bookkeeping one idempotent PostgreSQL transaction. It adds a
persisted posting intent, an explicit acknowledgement timestamp, usage fields
for the existing chapter/micro-topic/source entities, and three service-only
RPCs:

- `record_quiz_post_intent`
- `finalize_quiz_post`
- `record_quiz_post_unknown`

The finalizer locks the quiz run, verifies a checksum-certified ten-question
pack, accepts an idempotent replay with the same Telegram message ID, rejects a
conflicting message ID, and updates the run, question reuse dates, chapter
history, and existing taxonomy/source usage together or not at all.

## Deployment order

1. Run unit, type, style, and database-integration tests against the current
   schema upgraded through this migration.
2. Record staging migration history and aggregate row counts. Do not log quiz
   content, learner data, tokens, or service credentials.
3. Apply this one unapplied migration to staging through the normal migration
   workflow.
4. Deploy the exact tested application commit to staging.
5. Require `/health/ready` to report the expected post-finalization migration
   version and `checks.postFinalization=true`.
6. Post one staging quiz, verify its Telegram message ID and acknowledgement
   timestamp, and verify one-time usage/history increments.
7. Reinvoke `finalize_quiz_post` with the same message ID and confirm
   `idempotent_replay=true` with no second increments.
8. Apply the same migration to production before deploying the application.

## Reconciliation policy

- `posted`: the acknowledgement and all bookkeeping committed.
- `posting_failed`: Telegram clearly rejected the send; normal retry policy may
  retry it.
- `posting_unknown`: delivery may have happened, or acknowledgement succeeded
  but database finalization failed. Never resend automatically. Verify the
  Telegram topic/message first, then reconcile deliberately.
- A different Telegram message ID for an already finalized quiz is an error,
  not a second post.

## Preservation and rollback

The migration adds columns and functions and updates rows only when a finalizer
is invoked. It does not delete or rewrite existing quiz, attempt, score,
leaderboard, report, or learner rows. The service-role grants are intentionally
fail-closed; `PUBLIC`, `anon`, and `authenticated` cannot execute the write
RPCs.

If the application must roll back, keep this migration applied; older code can
ignore the additive columns. Correct a database defect with a new forward
migration. Do not edit or reapply an already-recorded migration.
