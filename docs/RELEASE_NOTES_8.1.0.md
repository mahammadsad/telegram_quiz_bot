# Release 8.1.0 — Versioned exam and shared-test configuration

Phase E2 adds an exam-pattern layer without changing the existing ten-question
quiz identifiers, routes, or submission contract.

- Adds effective-dated, versioned `Exam → Stage → Paper → Section` entities
  with paper/section time, marks, negative marking, cutoff, navigation,
  mark-for-review, and auto-submit rules.
- Adds subject/chapter/micro-topic/knowledge-point syllabus weights with
  cross-hierarchy validation.
- Adds shared definitions and instances for `daily_quick`, chapter, subject,
  mixed, previous-year, sectional-mock, and full-mock tests.
- Represents every existing and future daily ten-question quiz as a
  `daily_quick` instance while preserving quiz, mapping, attempt, and answer
  identifiers.
- Exposes paginated effective exam/definition catalogues and answer-free public
  test instances through the server-side API.
- Keeps all new tables and SQL functions service-role-only and makes version,
  historical-link, permission, and readiness checks fail closed.

Only the verified `daily_quick` behaviour is published. Other test definitions
remain explicit drafts until reviewed exam authority, paper, section, timing,
and marking rules are loaded as a new version.
