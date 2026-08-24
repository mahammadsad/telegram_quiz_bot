# Quiz delivery SLO diagnostic

`scripts/report_quiz_delivery_slo.py` derives a bounded operational report from
the append-only durable quiz-job history. The default window is 14 days and the
maximum is 31 days.

Definitions:

- expected jobs: 13 subjects for every calendar day in the requested window;
- complete delivery: a durable job reached `posted`;
- on-time delivery: `posted_at` is no later than 30 minutes after `due_at`;
- terminal failure: `blocked`, `posting_unknown`, or `dead_letter`;
- missing: no durable job exists for that date and subject.

The report contains dates, subject keys, status counts and aggregates only. It
does not select quiz IDs, content, answers, learner identifiers, worker IDs or
Telegram message IDs. It is read-only and requires the same explicit Supabase
project-identity check as other production diagnostics.

Run it with production credentials already present in the environment:

```bash
python scripts/report_quiz_delivery_slo.py --days 14
```

The diagnostic does not fail a release by default because formal availability
targets have not been approved. Operators may use `--fail-on-terminal` for a
deliberate incident check. External tracing and an independently monitored alert
delivery path remain required before this is a complete observability system.

The `Quiz Delivery SLO` workflow runs the same read-only report after the daily
quiz window and retains the aggregate JSON artifact for 30 days. Its schedule is
diagnostic redundancy, not the primary quiz-delivery control plane.
