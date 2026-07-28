# Source-backed rotation v1 rollout

- Application: `7.1.0`
- Database contract: `2.2.0`
- Required structural migration: `20260724212939`
- Source-rollout migration: `20260728040209`

This is a forward-only chapter-state and contract migration. It changes no
historical quiz, attempt, answer, report, ranking, review, source, or resource
row.

## Exact order per environment

1. Confirm the protected environment and exact Supabase project ref.
2. Record all existing table counts and the migration ledger.
3. Run **Static Source Rollout** with `operation=validate`.
4. Run it with `operation=import` only after the exact acknowledgement gate.
5. Run **Current Affairs Sources** with `operation=validate`.
6. Run it with `operation=refresh` only after the exact acknowledgement gate.
7. Verify every selected chapter has a current verified source.
8. Apply only `20260728040209_source_backed_rotation_v1.sql`.
9. Verify the contract reports:
   - `ready=true`;
   - `source_rollout_migration_applied=true`;
   - `source_backed_rotation_ready=true`;
   - `source_coverage_ready=true`;
   - required migration `20260724212939`;
   - source rollout `20260728040209`.
10. Deploy the exact CI-tested `7.1.0` commit with
    `SOURCE_BACKED_ROTATION_ENABLED=true`.
11. Run sanitized preflight. Do not use either force flag.

For the two write operations, copy exactly one matching phrase:

- Staging static import:
  `IMPORT REVIEWED SOURCES TO STAGING prdrabmcivgbygzjnmko`
- Production static import:
  `IMPORT REVIEWED SOURCES TO PRODUCTION tizxodkcpglmxgtwepor`
- Staging PIB refresh:
  `REFRESH PIB SOURCES IN STAGING prdrabmcivgbygzjnmko`
- Production PIB refresh:
  `REFRESH PIB SOURCES IN PRODUCTION tizxodkcpglmxgtwepor`

Use this order in staging first. Do not proceed to production if source
coverage, identity, permissions, migration state, health, or public-data checks
fail.

## Staging evidence

- All static and dynamic source validators pass.
- PostgreSQL 17 applies every migration and the exact 31-key rotation matches
  the allowlist.
- The read-only source preflight proves every selected chapter has grounding.
  A missing source must have zero Gemini,
  quiz-run, database-write, and Telegram side effects.
- Public quiz payloads contain ten questions and four options each, with no
  answer or explanation fields.
- One normal Telegram quiz completes the draft-recovery and submission
  lifecycle. A retry does not regenerate or repost.
- `/health/live` and `/health/ready` return HTTP 200 after certification.

## Production activation

Repeat the source import, current-affairs refresh, migration, contract, and
preservation-count checks against production. Set the production scheduler
repository variable `SOURCE_BACKED_ROTATION_ENABLED=true` only after every
check passes. Set the Render environment flag true and verify readiness.

Observe the next normal scheduled 07:00–19:00 IST cycle. Confirm one post per
subject, no duplicate run/client-attempt/post groups, provider fallback only
for retryable failures, and no certified-pack regeneration. Do not use
`force_post` or `force_regenerate`.

## Stop and recovery

If a source is absent or stale, leave the flag false or return it to false.
That is the safe operational pause and does not modify data. Do not reverse the
migration or weaken RLS. A factual correction is a new immutable source fact
version; it never overwrites a verified fact used by an existing question.
