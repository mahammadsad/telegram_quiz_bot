# 8.7.8

- The syllabus now reports the same chapter rotation used by quiz generation.
  Historical catalogue flags incorrectly advertised five unavailable
  current-affairs chapters and omitted Economy/Reports. The public projection
  follows all three approved chapters and the configured stable-subject gate.
  Rotation eligibility remains distinct from question inventory or mastery.
- Public syllabus discovery no longer waits for private progress. A slow or
  failed progress request leaves the catalogue usable and presents a Bengali
  recovery action. Retrying progress preserves filters, expanded chapters and
  keyboard focus; anonymous visitors still see no invented private progress.
- ISRO refresh inspects all candidates within its item budget, even after an
  expired entry. Pinned or reordered index entries no longer hide a later fresh
  release. Existing host, publication-date and exact-evidence checks still apply.
- An empty, stale or invalid RBI feed reports `available_no_current_rows`,
  matching the other official adapters, instead of implying usable coverage.
- Returning browser/PWA clients receive shell `8.7.8-ui1` through the tested
  service-worker upgrade path.

Regression evidence: six Python cases and the delayed-progress browser case
failed before their fixes. Targeted Python, mobile layout and accessibility
checks pass after the changes. Protected CI and staged deployment remain the
release gates; local checks alone do not establish production success.

## Deployment evidence

- Protected Tests `33978359959` passed 802 Python tests, 308 mobile-browser
  tests and six HTTPS service-worker tests. Security `33978359990` passed.
- Candidate `0af5c6a088e82414946935f99efc5fb1afab5a99` passed authenticated
  staging smoke `33978692499`. Staging rolled back to 8.7.7 commit
  `019fd21341afa630cdb7603975764274f595f66c` and passed liveness, readiness
  and authenticated smoke `33978857895`. The candidate was restored and passed
  those health gates and authenticated smoke `34003536542` again.
- Production serves merge commit `653f22b6da7bce8d423dffced92d3479cb322a36`:
  version 8.7.8, liveness and readiness HTTP 200, and exactly the three reviewed
  current-affairs chapters in the public syllabus. Canonical production smoke
  `34003727479` passed against posted quiz `20260905-current-affairs`.

No database migration is required. Application rollback targets
`019fd21341afa630cdb7603975764274f595f66c` (8.7.7); leave the existing
platform 1.5.0 database contract and migrations in place. New current-affairs
chapters still require fresh reviewed evidence before activation. Real Telegram
and Bengali assistive-technology checks remain manual acceptance work.
