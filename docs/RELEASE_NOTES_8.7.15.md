# 8.7.15 — candidate

P0-02 / P1-02 / P2-01: prevent repeatedly rejected replenishment jobs from
blocking every later topic in their subject.

## Evidence

Read-only production history on 12 September found five consecutive Mathematics
claims since the just-in-time worker release, all for
`mathematics:average-age:t04`. Each completed with zero accepted and ten rejected
candidates. Thirty eligible jobs across eight Mathematics chapters were still
waiting. The twice-nightly schedule is longer than the capped retry delay, so
the oldest job was eligible again every time. Sorting by its unchanged original
due time kept selecting it. This is not evidence that Mathematics received no
subject-level worker slots; it received five.

Protected inventory report `34663850675` measured 189 eligible Mathematics
questions but only two complete chapter difficulty mixes out of sixteen. The
10 September daily Mathematics job also exhausted validation retries and remains
an unreplayed dead letter. Its final failure was independent answer/explanation
rejection, not the topic-routing defect repaired in 8.7.14.

## Change and boundaries

- Aggregate existing append-only claim events once, sharing their recency
  between target and subject ranking. Within each subject, unclaimed targets
  come first, followed by the least recently claimed eligible target.
- Use durable event IDs as a tie-break when transaction timestamps are equal.
  Completion clears `claimed_at`, so that transient job field cannot implement
  lasting rotation.
- Within each unchanged reserve tier and subject round, prefer least recently
  claimed subjects before the size of their deficit. This preserves fairness
  across successive single-job RPC calls, not only a multi-job batch.
- Keep due/retry/lease eligibility, reserve threshold, `SKIP LOCKED`, exclusive
  ownership, 1–25 limits and 5–120 minute lease bounds unchanged. Do not reset
  retry history, waive verification, approve sources or publish synthetic quizzes.

Migration `20260912132928_durable_replenishment_job_rotation.sql` replaces only
the existing service-only claim function. The signature and row contract remain
compatible with 8.7.14. No new table, index, source approval, frontend or Telegram
change is required. Reuse the existing partial claim-event index; measure the
read-only ranking plan before hosted promotion.

Release gates: disposable PostgreSQL tests comparing the pinned legacy function
with the new behavior, full CI/security/mobile checks, staging source/permission
readback and a bounded canary, guarded production migration plan/apply/readback,
authenticated app rollback/restore and exact-SHA production smoke. The new
migration source must not enter the production ledger pin until its production
apply has been verified.

## Rollback and remaining work

Application rollback is `a8b79650e655d21f33e43f5a1b987804b29ba4df` (8.7.14),
retaining the compatible migration. Application rollback does **not** revert
database claim ordering. If that behavior itself needs reversal, use a reviewed
forward migration restoring only the previous claim-function definition from
`20260904172137_reserve_tier_round_robin_claims.sql`; do not replay its separate
platform-contract renames, delete migration history, or erase jobs/events.

This enables other eligible topics to receive work; it does not turn rejected
questions into valid ones or guarantee a complete quiz from each batch. Source
breadth, mathematical proof quality and live on-time delivery remain unfinished.
