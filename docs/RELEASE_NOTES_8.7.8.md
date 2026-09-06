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

No database migration is required. Application rollback targets
`019fd21341afa630cdb7603975764274f595f66c` (8.7.7); leave the existing
platform 1.5.0 database contract and migrations in place. New current-affairs
chapters still require fresh reviewed evidence before activation. Real Telegram
and Bengali assistive-technology checks remain manual acceptance work.
