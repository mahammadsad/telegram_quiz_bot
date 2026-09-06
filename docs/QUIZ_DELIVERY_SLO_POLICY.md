# Quiz delivery SLO diagnostic

`scripts/report_quiz_delivery_slo.py` derives a bounded operational report from
the append-only durable quiz-job history. The default window is 14 days and the
maximum is 31 days.

By default the final date is the latest closed daily delivery window in
`Asia/Kolkata`, independent of the runner's timezone. A window closes after the
last configured quiz slot plus the 30-minute on-time allowance (currently
19:30 IST). Morning/manual runs therefore report through yesterday; the normal
21:00 IST scheduled run includes today's completed schedule. This prevents
future jobs from being counted as failed delivery or active retries. Missing or
late jobs in a closed window remain visible and still fail the same objectives.

Use `--end-date YYYY-MM-DD` for an explicit historical or in-progress snapshot.
An explicitly selected unfinished day includes all 13 expected jobs and can
miss objectives while some jobs are still legitimately waiting for their slots.

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
diagnostic redundancy, not the primary quiz-delivery control plane. A deliberate
manual run can select `enforce_slo`; scheduled runs always remain non-blocking.
