# Release 7.5.0 — Phase D current-affairs evidence pipeline

This release candidate is staging-only until its additive database migration,
CI, mobile-browser, and public readiness gates pass.

## What changed

- Added stable current-affairs event clusters with event dates distinct from
  source publication/update dates.
- Added exact-span atomic claims, multi-source corroboration links, claim-level
  validity/expiry, correction/supersession state, and append-only review events.
- Added an explicit authoritative-domain registry including PIB, RBI, ISRO,
  ECI, Supreme Court, SEBI, and West Bengal government sources.
- Added configurable category weights and daily, weekly, monthly, and important
  six-month revision pools.
- Routed current-affairs grounding through verified event/claim evidence while
  preserving the previous source path as a rollback-compatible fallback.
- Automatically parsed correction-like releases remain review-required; an
  authentic official document is no longer conflated with a verified claim.

## Database

Apply `20260808140855_phase_d_current_affairs_events.sql` after all earlier
migrations. The migration is additive, enables RLS on every new table, revokes
browser-role access, and exposes only service-role RPCs.

## Production safety

No production schema, service, schedule, or Telegram delivery is changed by
publishing this release candidate branch. Production promotion requires a new
explicit release decision after staging evidence is reviewed.
