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

Pre-release verification (13 September IST): 931 protected Python/database
tests, 336 mobile tests and 6 service-worker tests passed for `4b7af56`.
Staging migration source MD5 `aedfc1cf07a0ca76d807425381565c32` and service-only
permissions were read back; advisors reported no warnings/errors. Initial
canary `34697038030` stopped on an HTTP 504 during schema validation, before
any claim. Readback confirmed zero claim events before its single retry.
Attempt 2 passed: English 3 accepted / 2 rejected, Environment 5 accepted /
0 rejected, with each claim following the preceding completion. It did not
publish to Telegram or prove production Mathematics coverage. Candidate
staging deploy `dep-daisdvgae00c73fp30p0` and authenticated lifecycle smoke
`34720718216` passed. Read-only production plan `34697098474` contained only
this migration; production application is still 8.7.14.

The runbook backup requirement was not enforced by migration automation.
Plan/apply workflows now check the exact production project's Management API
for a completed backup within 48 hours and fail closed on missing, stale or
unavailable evidence. No backup data, identifiers or credentials are printed,
downloaded or restored. This does not certify a restore drill or authorize
destructive recovery. The updated candidate must repeat CI and staging gates;
production migration/source pin and promotion remain pending.

Updated read-only plan `34720837430` passed project identity, source parity and
the single-migration preview, then blocked on no completed provider backup
within 48 hours. Readback confirmed the production claim-function hash is still
`0ed3bbfb756fe88eb45d8e9d937b8a9c`, platform readiness is true and the rotation
migration is absent. All 65 production pins remain unchanged. Staging rollback
`dep-daisf7p5efls73eoufkg` and authenticated smoke `34720849074` passed while
retaining the new compatible staging function. No paid plan, backup restore,
production DDL or historical quiz replay was initiated.

Application rollback is `a8b79650e655d21f33e43f5a1b987804b29ba4df` (8.7.14),
retaining the compatible migration. Application rollback does **not** revert
database claim ordering. If that behavior itself needs reversal, use a reviewed
forward migration restoring only the previous claim-function definition from
`20260904172137_reserve_tier_round_robin_claims.sql`; do not replay its separate
platform-contract renames, delete migration history, or erase jobs/events.

This enables other eligible topics to receive work; it does not turn rejected
questions into valid ones or guarantee a complete quiz from each batch. Source
breadth, mathematical proof quality and live on-time delivery remain unfinished.
