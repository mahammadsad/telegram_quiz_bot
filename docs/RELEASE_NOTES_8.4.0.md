# Release 8.4.0 — Resilient low-data Mobile Mini App

## Learner experience

- Adds a lightweight timed multi-section mock view with question palette, marked-for-review state, section transitions, submit confirmation, auto-submit, and section/subject/topic results.
- Saves mock answers locally before network synchronization and reuses the same client attempt identity across refreshes and retries.
- Makes loading, empty, offline, synchronization-error, retry, and ambiguous-submit states explicit.
- Keeps the advertised interface locale Bengali-only until complete Hindi and English translations are available.

## PWA and answer safety

- Caches only the static Mini App shell and server-marked answer-free quiz/test projections.
- Never puts authenticated attempts, progress writes, results, leaderboards, personal data, admin data, explanations, or answer keys in Cache Storage.
- Adds a private `X-Answer-Free-Payload` contract to the two public pre-submission projections.

## Accessibility and low-data behavior

- Adds a skip link, consistent visible focus treatment, offline announcements, reduced-motion support, scalable text, and 44px touch targets.
- Uses the existing dependency-free HTML/JavaScript architecture and a small shared shell instead of a client framework.

## Deployment boundary

- No database migration is required for this release; it consumes the existing versioned test-definition and timed-attempt APIs.
- Production remains unchanged until the staged exact-commit release gate is approved.
