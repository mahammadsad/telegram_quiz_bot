# Question calibration policy

This control produces advisory, answer-free classical item diagnostics. It does
not publish, retire, rewrite, or reclassify a question and it does not alter a
learner's mastery. A qualified content and learning-science reviewer remains
responsible for every consequential decision.

## Evidence boundary

- Use a rolling 90-day window and only completed first attempts.
- Count at most one response per learner and question, keeping the earliest.
- Read at most 50,000 answer rows in pages of 1,000.
- Require at least 100 responses and 50 unique learners per question.
- Require at least 10 correct and 10 incorrect responses before interpreting
  discrimination.
- Report only aggregates and question IDs. Learner IDs, attempt IDs, selected
  option indexes, correct option indexes, stems, and option text are excluded.

The initial thresholds are conservative engineering gates, not a claim of
scientific validation. They must be reviewed against the platform's exams,
population, test lengths, and sampling bias before they drive policy.

## Metrics and review signals

- Facility is the first-response correct proportion with a Wilson 95% interval.
- Discrimination is the point-biserial correlation between item correctness and
  the rest-of-test score. Values below 0.10 request editorial review; negative
  values receive a distinct reason code.
- A distractor selected by fewer than 5% of answered observations is flagged as
  nonfunctioning. Distractor shares are sorted and detached from option indexes
  in the output so the report cannot act as an answer key.
- Facility below 0.20 or above 0.90 requests review.
- Authored `easy`, `medium`, and `hard` labels are flagged when observed facility
  falls outside the provisional ranges `>= 0.70`, `0.35–0.80`, and `<= 0.55`.

Until all sample gates are met, the only recommendation is
`collect_more_data`. With adequate evidence, the tool emits `retain` or
`editorial_review`; neither recommendation performs a database write.

## Operator command

Run this only in a protected server environment with `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, and `EXPECTED_SUPABASE_PROJECT_REF` configured:

```bash
PYTHONPATH=. python scripts/report_question_calibration.py
```

The ownership guard fails closed if the URL does not match the expected project.
Treat output as restricted operational analytics even though it is answer-free.
