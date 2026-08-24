# Quiz quality migration — 20260728113750

Application: `7.2.0`

Migration:
`supabase/migrations/20260729105500_quiz_quality_and_negative_marking.sql`

## Deployment order

1. Run the full CI suite against a disposable PostgreSQL 17 database.
2. Apply the migration to staging.
3. Verify the sanitized contract fields:
   - `quiz_quality_migration_version=20260728113750`;
   - `quiz_quality_migration_applied=true`;
   - `diverse_grounding_ready=true`;
   - `negative_marking_ready=true`;
   - `ready=true`.
4. Generate one new staging quiz normally, without force flags.
5. Confirm ten integrity-verified questions, the required source/topic
   diversity, one post, answer-free public data, and net-score submission.
6. Apply the exact CI-tested migration to production.
7. Deploy the exact CI-tested application commit.
8. Confirm `/health/live` and `/health/ready` return HTTP 200 before allowing
   the next normal scheduler cycle.

## Preservation contract

- No question, source, resource, attempt, answer, review, ranking, or quiz-run
  row is deleted or rewritten.
- Existing quiz runs receive a zero penalty and retain historical scoring.
- Only quiz runs inserted after the migration default to a `0.25` wrong-answer
  penalty.
- Neither `force_post` nor `force_regenerate` is needed for this migration.
