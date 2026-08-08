# Release 8.0.0 — Personal knowledge mastery

Phase E moves personalized revision from question variants to stable knowledge
points while preserving every existing question-level API.

- Tracks mastery, lapses, skips, response time, and the 1/3/7/14/30/60-day
  revision schedule per learner and knowledge point.
- Keeps immutable learner variant history and selects a different verified
  variant for revision whenever one is available.
- Adds paginated daily rollups for answered, skipped, net-score, and timing
  trends without exposing answer keys.
- Extends the authenticated dashboard with weakest and strongest knowledge
  points, a transparent 50/30/20 recommendation policy, a next action, and an
  explicit leaderboard cohort definition.
- Keeps learner tables and RPCs service-role-only with fail-closed readiness
  and deployment contract checks.
