# 8.7.10

- A timed-out or unavailable repair model can use the exact generator that
  already returned the initial candidate, within the existing per-key attempt
  budget. This regenerates a full batch and retains all validation, duplicate
  checks and the separately pinned independent verifier. Quota, authentication,
  malformed-request and safety handling are unchanged.
- The exact question-variant uniqueness violation is now classified as a
  retryable content collision, preserving durable chapter rotation. Unrelated
  database constraints and permission failures still propagate unchanged.
- No timeout, retry budget, content-quality gate, scheduler, migration or
  frontend cache contract is changed. Shell assets remain 8.7.9-ui1.

Regression tests cover timeout recovery through the full generation pipeline,
rejection of an invalid replacement, verifier pinning, bounded attempts and
structured database error classification. Actual production timing improvement
still requires observing normal dispatch; historical late jobs are already
posted and must not be replayed.

Rollback: deploy `182b9c07268776869e045cf6c1f577149bd8018f` (8.7.9), retaining
all platform 1.5.0 migrations. Protected CI, exact-SHA staging, rollback and
production smoke remain release gates.
