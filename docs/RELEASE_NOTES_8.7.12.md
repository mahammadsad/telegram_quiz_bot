# 8.7.12 — candidate, not yet deployed

Difficulty-aware replenishment addresses P0-02/P1-02/P2-01 content coverage.
The September 9 inventory report found Computer chapters with 19–20 verified
questions but zero hard questions and no open replenishment job. The previous
12-question topic threshold hid these chapter-level shortages.

- Queue eligibility additionally checks the chapter's 3 easy / 5 medium / 2 hard
  minimum, using the inventory's verified question/source/supporting-fact rules.
- Existing source approval, active chapter/topic and current-affairs rotation
  gates remain unchanged. Batches stay at 3–5 questions and jobs target 15.
- Optional bundle counts steer generation toward missing levels. Malformed
  counts fail closed; older bundles retain their balanced prompt. Question
  difficulty is never relabelled and independent verification is unchanged.
- Newly inserted jobs are returned directly alongside already-open jobs,
  including mixed old/new queues in a single statement snapshot.
- The new aggregate and backing source RPC are service-role-only. No browser
  endpoint, learner data, Telegram publication or UI cache contract changes.

Migration: `20260909040332_difficulty_aware_replenishment.sql`. Platform contract
remains 1.5.0: this is backward-compatible optional bundle metadata, not a new
required application schema. The 64 existing production ledger source pins
remain untouched until a production apply and readback establish the 65th.

Release gates: disposable PostgreSQL chain and behavioral tests; full CI;
staging migration and permission/plan checks; exact-SHA lifecycle smoke and
8.7.11 rollback/restore; reviewed production migration plan/apply; deployment
health and public smoke. None of these is implied by this candidate note.

Rollback application to `24d549a2c93c27347de4aad6e73497787131519e` (8.7.11),
retaining this additive migration. If queue eligibility itself must be reverted,
restore the previous private ensure function body from the immutable
`20260830095000_source_optional_stable_replenishment.sql` under its current
`ensure_due_content_replenishment_jobs_source_optional_base` name using a new
reviewed forward migration. Do not delete questions/jobs or rewrite ledger rows.

Remaining: actual hard-question yield depends on suitable reviewed evidence and
verifier acceptance; this does not certify complete syllabus or exam coverage.
