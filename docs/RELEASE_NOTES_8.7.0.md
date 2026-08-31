# Release notes — 8.7.0 Mini App reliability and learner experience

## Outcome

This release closes the highest-risk Mini App reliability and usability gaps
identified in the 2026-08-31 audit. It keeps one browser request owner, adds
truthful learner-facing states, reduces authenticated bootstrap round trips,
and standardizes the mobile navigation and Citizen Affairs Bengali identity.

## Reliability

- Centralized typed Mini App transport with bounded safe retries and a 30-second
  initial read budget suitable for Render cold starts.
- Removed the service worker's competing API timeout; authenticated and
  answer-bearing API traffic is always network-only.
- Added request correlation, aggregate database timing, safe per-operation
  timing labels, and `Server-Timing` output.
- Added one-RPC dashboard and practice bootstraps and throttled Telegram user
  activity writes.
- Added production-contract gating for migration `20260831011657` and platform
  contract `1.1.0`.

## Learner experience

- Replaced raw transport errors with actionable Bengali loading, slow, offline,
  authentication, rate-limit, temporary-service, empty, and completion states.
- Standardized the four global destinations: Quiz, Practice, Progress, and
  Settings.
- Moved Due, Wrong, Bookmarks, and Weak Topics into an accessible Practice
  source switcher; Weak Topics can select the learner's weakest subject.
- Kept exactly one primary bottom action visible during active quiz and practice
  sessions, including safe-area and keyboard-height layouts.
- Improved quiz question-map and settings dialogs, dirty-save behavior,
  destructive-action separation, focus handling, and WCAG 2.2 AA coverage.
- Applied `CITIZEN AFFAIRS বাংলা`, brand colors, responsive safe areas, and the
  Citizen Affairs website CTA across learner surfaces.

## Verification gates

- Python unit/static/contract suite.
- Ruff, mypy, JavaScript syntax, lockfile parity, migration-source integrity,
  and whitespace checks.
- Playwright mobile matrix at 320×568, 360×800, 390×844, and 412×915.
- Local HTTPS service-worker regression suite, including a 24-second cold quiz
  response.

Production rollout remains database-first: apply and verify the new migration,
then deploy the application at the same reviewed commit and run the staging and
production smoke workflows.
