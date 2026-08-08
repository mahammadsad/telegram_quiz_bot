# Release 8.2.0 — Real previous-year provenance and timed mocks

Phase E3 adds an audited previous-year question model and a generalized timed
attempt engine while preserving the existing daily quiz API and identifiers.

- Separates verified actual previous-year questions from generated
  previous-year-style practice.
- Records exam/stage/paper/section, year, shift, original question number,
  official-answer status, source checksum, licence, language, and human review.
- Applies corrections through append-only records tied to an explicit
  superseding question version; future-dated corrections fail closed.
- Adds UUID-idempotent test attempts, timed section state, exact forward section
  transitions, autosave, mark-for-review, section-specific marking, and
  manual/automatic submission.
- Defines ranking as first submitted attempts by distinct learners on the same
  test instance and returns subject, topic, and knowledge-point analysis.
- Mirrors historical and future daily quiz attempts/answers into the shared
  model without replacing or renumbering legacy records.
- Exposes answer-free previous-year browsing and owner-authenticated attempt
  start, progress, transition, submission, recovery, and post-submit review.
- Keeps every new table and function service-role-only behind RLS, with a
  fail-closed readiness contract and exact migration/version checks.

Actual previous-year tests still require verified provenance for every mapped
question. The previous-year-style definition remains a draft and cannot be
labelled as an actual PYQ.
