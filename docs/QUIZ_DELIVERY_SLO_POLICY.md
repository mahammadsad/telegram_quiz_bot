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

Policy version 1 defines non-contractual engineering objectives for every
rolling report window:

- at least 99% delivery completeness;
- at least 95% delivery within the 30-minute grace period;
- no missing durable jobs;
- no unknown-delivery jobs;
- terminal failures at or below 1% of expected jobs.

The JSON includes each objective, each pass/fail result and one `overallMet`
result. These are internal reliability targets, not a public availability SLA.

Run it with production credentials already present in the environment:

```bash
python scripts/report_quiz_delivery_slo.py --days 14
```

The diagnostic does not fail a release by default while the platform builds a
representative baseline. Operators may use `--fail-on-terminal` for a deliberate
incident check or `--fail-on-slo` to enforce every versioned objective. External
tracing and an independently monitored alert delivery path remain required before
this is a complete observability system.

The `Quiz Delivery SLO` workflow runs the same read-only report after the daily
quiz window and retains the aggregate JSON artifact for 30 days. Its schedule is
diagnostic redundancy, not the primary quiz-delivery control plane.
