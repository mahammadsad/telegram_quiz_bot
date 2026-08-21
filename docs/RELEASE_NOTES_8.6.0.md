# Release notes — 8.6.0 production-readiness and preparation hub

- Adds authoritative server-timed daily attempts and keeps client timing only
  as an explicitly untrusted diagnostic signal.
- Separates question generation from independent verification and records the
  verification contract durably.
- Adds a discoverable learning-test catalogue and a useful full-mock landing
  state when no test UUID is supplied.
- Adds authenticated data export, account-deletion request/cancellation, and
  public privacy/terms destinations.
- Exposes immutable release identity for deployment and rollback smoke tests,
  and makes Mini App/PWA paths work below a non-root hosting prefix.
- Replaces the broken no-deep-link root state with a Bengali preparation hub,
  backed by a bounded answer-free catalogue of certified posted quizzes.
- Keeps revision, full mock, and personal-progress entry points usable when the
  recent-quiz catalogue is offline, and caches only its safe public projection.
- Covers durable job subject foreign keys, isolates `pg_trgm` in the extensions
  schema, and removes the historical duplicate normalized-text GIN index.

Promotion remains staging-first under `docs/PRODUCTION_RELEASE_AND_ROLLBACK.md`.
