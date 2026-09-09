# 8.7.12

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
remain untouched; the 65th was added only after production apply and readback.

Release gates: disposable PostgreSQL chain and behavioral tests; full CI;
staging migration and permission/plan checks; exact-SHA lifecycle smoke and
8.7.11 rollback/restore; reviewed production migration plan/apply; deployment
health and public smoke. Production application deployment is pending until
the exact final commit completes these gates; completion evidence belongs in PR #107.

Verified pre-release evidence (9 September 2026):

- Candidate `7489e5ffa6e52ffb614f4ea036082c179f712a3a`: Tests `34310102037`,
  Security `34310102030`; 897 Python tests including all 65 migrations and
  rollback-only synthetic database fixtures; 336 mobile and 6 service-worker
  tests. Local suite: 844 passed / 53 database tests skipped. Ruff, mypy (91
  files), lock parity and public-data history scan passed.
- Exact staging deploy `dep-dagdrgu7bikc73ao6t00` and authenticated lifecycle
  smoke `34310468249` passed. Bounded staging replenishment `34310360392`
  claimed one Computer job: 4 accepted / 1 rejected, no Telegram publication.
  Readback confirmed generator attribution, independent verification,
  deterministic unique-answer proof and difficulty match for all four. This
  was an empty chapter's 2 easy / 3 medium target; it is not proof of live hard
  question yield in the affected production chapters.
- Read-only production plan `34310230116` contained exactly the one reviewed
  migration. Protected apply `34310571247` passed RPC/platform/privacy/reminder
  checks. Production records version `20260909040332`; staging's tool-generated
  ledger version is `20260909041549`. The staging single-statement source hash
  matches repository MD5 `3403560a5215fbb4407bcb4c17e93c81`. Production CLI splits
  it into 12 statements; all four `pg_get_functiondef` hashes and permissions
  match staging exactly. No ledger rows were rewritten.
- Security/performance advisors reported informational service-only RLS and
  unused-index notices, with no warnings/errors. No speculative indexes or
  public policies were added. A read-only production query-plan check reduced
  catalogue fanout by filtering eligible inventory once before the join.

Rollback application to `24d549a2c93c27347de4aad6e73497787131519e` (8.7.11),
retaining this additive migration. If queue eligibility itself must be reverted,
restore the previous private ensure function body from the immutable
`20260830095000_source_optional_stable_replenishment.sql` under its current
`ensure_due_content_replenishment_jobs_source_optional_base` name using a new
reviewed forward migration. Do not delete questions/jobs or rewrite ledger rows.

Remaining: actual hard-question yield depends on suitable reviewed evidence and
verifier acceptance; this does not certify complete syllabus or exam coverage.
