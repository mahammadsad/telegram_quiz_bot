# Release 8.3.0 — Audited question quality administration

Phase E4 turns learner reports into an abuse-resistant, reviewable content
workflow without changing existing quiz or attempt identifiers.

- Retains every existing report reason and adds `duplicate_question` and
  `translation_error` to daily and revision reporting.
- Counts distinct authenticated learners linked to completed attempts, applies
  durable rate limits, and discounts configured risk profiles, shared abuse
  clusters, and suspicious report bursts.
- Quarantines a question when the configurable independent-report threshold is
  reached and immediately quarantines an administrator-confirmed deterministic
  contradiction or authoritative correction.
- Requires authoritative corrections and confirmed replacements to reference
  an explicit superseding immutable question version.
- Adds a minimal protected admin queue with start-review, confirm, dismiss,
  supersede, and reinstate decisions.
- Preserves append-only report and moderation event history, including reviewer,
  reason, resolution, replacement version, and the declared score effect.
- Uses `preserve_historical` as the initial transparent score/rank policy;
  historical attempts are never silently rewritten.
- Keeps moderation tables and answer-bearing queue payloads service-role-only
  behind RLS and an exact fail-closed readiness contract.

This release intentionally does not add a large CMS or expose moderation data
to learners. Production remains gated on the final staging and rollout review.
