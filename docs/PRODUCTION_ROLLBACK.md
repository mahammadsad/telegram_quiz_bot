# Production backup and rollback runbook

Production changes are forbidden until the complete staging checklist passes.
The only production database in scope is `telegram_group_data` with project ref
`tizxodkcpglmxgtwepor`.

## Pre-deployment checkpoint

Through the secure provider interfaces, record without exposing connection
values:

- production project name/ref and region/status;
- current application commit and Render deployment identifier;
- ordered migration ledger and current contract response;
- counts for users, questions, quiz runs, submissions, quiz attempts,
  attempt-answer rows, reports, source documents, bookmarks, preferences,
  practice answers, and review schedules;
- identifiers/status/checksum metadata for representative historical quizzes;
- the provider backup/checkpoint identifier, creation time, retention, and
  restore availability;
- security and performance advisor findings.

Confirm the checkpoint is complete before applying SQL. A written procedure is
not a backup: the provider must report a real restorable checkpoint or approved
point-in-time-recovery boundary.

## Forward release

1. Pause production quiz/resource schedules.
2. Verify no staging URL, project ref, or credential name is present in the
   production service configuration.
3. Apply only unapplied files from `supabase/migrations/` in timestamp order.
4. Verify the exact ledger marker `20260724212939`, contract `2.2.0`, all
   required objects/grants/RLS/RPC signatures, and empty contract failure arrays.
5. Compare every preservation count and representative historical quiz with the
   checkpoint record. Any unexplained decrease is a stop condition.
6. Deploy the exact CI-tested commit, then require `/health/live` and
   `/health/ready` HTTP 200 before resuming one controlled cycle.

## Application rollback

If the database contract is ready but the new application fails:

1. Pause schedules and keep Telegram recovery disabled.
2. Redeploy the recorded previous application commit.
3. Leave additive database objects in place.
4. Verify liveness and the previous commit's supported critical reads.
5. Diagnose on a branch and deploy a corrective commit through the normal gate.

Do not drop new tables/columns/functions merely to match the old application.

## Migration failure recovery

If a migration fails before commit, confirm the provider rolled back the
transaction and recheck the ledger and preservation counts. Repair the cause in
a new timestamped migration when any part may have committed. Never edit an
already-applied migration or manually forge the migration ledger.

If a committed migration causes a schema defect but data is intact, keep
schedules paused and apply a reviewed additive corrective migration. Restore
the checkpoint only for unrecoverable corruption or deletion after identifying
the exact writes that would be lost. After restore, rerun the complete contract,
preservation, advisor, deployment, and controlled-lifecycle gates.

## Telegram recovery

For `posting_unknown`, inspect the intended forum topic first. If Telegram
accepted the original request, mark/reconcile the saved run without posting a
second message. Use an explicitly acknowledged manual force post only when the
topic proves the original message is absent. Never use bulk recovery as a
production smoke test.
