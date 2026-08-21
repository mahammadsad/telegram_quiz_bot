## Summary

Describe the learner/operator impact and linked issue.

## Trust and data review

- [ ] Public payloads contain no answers, secrets or private identity.
- [ ] Authentication, authorization, RLS, scoring, timing and privacy controls are not weakened.
- [ ] Content provenance/verification implications are documented.
- [ ] Migrations are additive, ordered and tested from the supported baseline.

## Verification

- [ ] Ruff and mypy
- [ ] Python tests and disposable PostgreSQL migrations
- [ ] Browser/accessibility checks where UI changes
- [ ] Dependency/security and public-data history scans
- [ ] Staging/deployed smoke and rollback plan where release behavior changes

## Rollout / rollback

State flags, migration order, monitoring, owner and exact rollback path.
