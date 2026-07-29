# Release notes — 7.2.1 learner dashboard and scheduler repair

Version 7.2.1 restores the learner dashboard and revision queue, and makes each
normal scheduled workflow create at most one subject quiz.

## Personal learning

- Dashboard statistics and performance graphs retain their complete JSON
  response shape while nested subject names are normalized.
- Due-review, wrong-question, bookmark, and learner-dashboard projections use
  the same recursive, private database helper.
- Readiness fails closed unless the repaired projection contract is installed.

## Scheduling

- GitHub Actions now has thirteen immutable hourly subject cron entries.
- Each normal cron maps to exactly one subject.
- The separate 20:30 IST recovery remains available for genuinely missed
  subjects and keeps the existing idempotency protections.

## Deployment safety

- GitHub workflows derive the public Supabase URL from the verified staging or
  production project identity.
- Service-role keys remain encrypted environment secrets.
- Existing quizzes, attempts, scores, and review schedules are not rewritten.
