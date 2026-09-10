# 8.7.14 — candidate

P0-02 / P1-02 / P1-11: route topic-distribution failures to the existing
distribution repair instructions, before the generic topic-identity matcher.

Read-only delivery report `34404035708` covers 3–9 September: all 91 quizzes
posted, but only 81 were on time (89.011%; target 95%). Production workflow
`34324505211`, job `102378589477`, records two Polity attempts rejected for
“Quiz micro-topics are not balanced across the grounded pack.” Both were
misclassified as `micro_topic`, so their repair instructed the model to copy
topic identifiers rather than redistribute questions. Their first claim was
timely; the quiz eventually posted 66.29 minutes after its due time.

Two regression cases reproduce this precedence bug before the change. Specific
diversity and balance markers now precede the generic `micro-topic` marker.
Actual validator failures reach the existing batch-wide distribution hint;
identity/source mismatch errors retain their identity hint, and structured
reason codes retain precedence. Generation-loop regressions confirm the same
single repair budget and fail-closed result if distribution is still invalid.

No validator, evidence requirement, source approval, content label, provider
budget, database contract, Telegram posting, or UI behavior is relaxed or changed.
This fixes an incorrect repair instruction, not every historical late delivery
or a measured live-model yield improvement. All three additional late jobs on
8–9 September are already posted and must not be replayed.

Release gates: full protected Python/database/static/security/mobile tests,
exact-SHA authenticated staging lifecycle, application rollback/restore, and
production health plus answer-free quiz smoke. Observe normal scheduled
generation before attributing a live delivery improvement; do not post a
synthetic quiz to learners solely to exercise an error branch.

Rollback application to `fc94faa09ee89b74274a26282b390ffd357d5116` (8.7.13).
Retain all 65 migrations and existing jobs/questions. Frontend shell remains
8.7.9-ui1 and platform contract remains 1.5.0.
