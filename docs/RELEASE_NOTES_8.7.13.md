# 8.7.13 — candidate

Addresses the P0-02/P1-02 durable inventory replenishment path. Code inspection
and clock-controlled tests exposed two timing risks: all jobs were claimed
before sequential model calls, and all retries used the run's initial time.
A failure 25 minutes into a run could therefore request a 15-minute retry that
was already ten minutes overdue. Later jobs spent their leases waiting for
earlier batches without any work being done on them.

- Claim exactly one job immediately before processing, retaining the database's
  reserve-priority, subject rotation and exclusive-ownership rules.
- Advance the run's logical start with monotonic elapsed time for each claim,
  grounding freshness check and retry. An explicit start time is not reused as
  a frozen timestamp throughout a long run.
- Preserve the existing 1–25 batch ceiling and 3–5 candidate batch size.
  A successful topic may be selected again if the database prioritizes it;
  reported `claimed` counts batches, while `outcomes` retains each topic's
  latest result. Empty queues stop immediately.
- If completion fails or its response is lost, propagate the error and stop.
  Do not issue another completion or claim more work after an ambiguous write.
  Existing persisted questions and durable ownership are not overwritten.

No new schema, source approval, verifier, difficulty-label, provider retry,
Telegram, reminder or UI changes. Platform remains 1.5.0 with 65 pinned
migrations and frontend shell 8.7.9-ui1. Supabase RPC ownership and privacy
checks are preserved; this changes orchestration, not database permissions.

Release gates: full Python/database/static/security/mobile tests, a bounded
two-batch staging canary, exact-SHA staging lifecycle, previous-version
rollback/restore, production health and answer-free quiz smoke. Candidate
status is not evidence that these release gates have completed.

Rollback application to `1dc389345cedc8d0b73515b25f55051a778db0f7` (8.7.12),
leaving all 65 migrations and existing questions/jobs intact.

Remaining: this prevents waiting jobs from aging under an unused lease; it
does not guarantee that a single unusually slow provider batch finishes within
the lease or workflow deadline. Process interruption still relies on durable
job recovery and novelty checks. Broader syllabus coverage, sustained delivery
SLOs, native Telegram/accessibility testing and owner-dependent approvals are
not certified by this worker fix.
