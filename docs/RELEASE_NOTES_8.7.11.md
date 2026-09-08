# 8.7.11

- Verified inventory candidates are no longer discarded when an optional
  replacement batch encounters a retryable generator/verifier outage, malformed
  generation or retryable verifier-response validation failure.
- Only candidates that already passed structural, deterministic, independent
  verification, identity and novelty checks can be retained. A failed new pass
  contributes no unverified questions. Zero-yield failures, authentication,
  safety and unexpected implementation errors continue to fail closed.
- Each saved question keeps its actual generator model from its server-created
  verification metadata, including batches containing accepted questions from
  different generation passes. The last model used no longer overwrites an
  earlier question's provenance.
- Bounded repair diagnostics distinguish generation and verification failures;
  failed generation attempts are counted, and repair invocation remains visible
  even when no replacement response arrives. No extra model calls are added.

No source, proof threshold, chapter activation, schema, hosting plan or frontend
cache contract changes. This repair does not claim complete syllabus coverage.
Protected CI, exact-SHA staging lifecycle and rollback checks remain release gates.

Rollback: deploy `324aef152efb677623f85d1bc9b2fd89828ff47c` (8.7.10), retaining
all platform 1.5.0 migrations and the 8.7.9-ui1 frontend shell.
