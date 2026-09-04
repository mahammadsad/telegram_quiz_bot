# Reserve-aware replenishment migration

Migration: `20260904164836_reserve_aware_replenishment_claims.sql`

## Purpose

The worker still claims at most 25 jobs and retains `FOR UPDATE SKIP LOCKED`,
but now orders due work by the live verified inventory gap before applying the
existing per-subject round-robin order. The safety reserve is 150 questions:
the versioned 15-day target at ten daily questions.

The capacity query deliberately matches the fail-closed verified-inventory
contract. Draft, expired, review-required, source-unverified, and
evidence-unverified rows cannot inflate a subject's reserve.

## Verification

After applying the migration:

1. `get_platform_contract_v1()` must report contract `1.2.0`, required
   migration `20260904164836`, `reserveAwareReplenishment: true`, and no
   missing checks.
2. `claim_content_replenishment_jobs` must remain `SECURITY INVOKER`.
3. `anon` and `authenticated` must not have execute permission; only
   `service_role` may execute it.
4. A transactional claim followed by rollback must claim a bounded,
   cross-subject batch without leaving a worker lease behind.
5. The inventory report after a bounded production run must show that the
   largest below-target subject gaps were selected before above-target
   chapter-diversity work.

## Rollback

Do not delete jobs or events. Apply a forward migration that restores the
function body from
`20260824052500_fair_content_replenishment_claims.sql`, advances the platform
contract again, and retains the same service-role-only grants. Existing
inventory, job history, accepted candidates, and append-only events remain
valid; only future claim ordering changes.
