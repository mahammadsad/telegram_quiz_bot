# 8.7.17 — candidate, not production-deployed

P0-02 / P1-02 follow-up: compare answer quantities without deleting the symbols
that distinguish them. This is stacked after the 8.7.15 queue migration and
8.7.16 settings/readiness release; it must not bypass their promotion gates.

## Reproduction and fix

The material-option check reused aggressive question-stem normalization, then
treated leading digits 1–4 as option labels. Valid choices `1.5, 2.5, 3.5, 4.5`
collapsed to the same value. Minus signs and decimal positions were also erased.
The earlier general validator separately conflated `-5` and `5`.

Fifteen new regressions failed before the fix, covering both false rejections
and missed duplicates. The new, shared answer-only comparison:

- preserves signed decimal quantities and fraction/ratio values;
- recognizes equivalent Bengali/Western digits, exact fractions/decimals,
  signed zero, supported digit grouping and same-unit numeric formatting;
- strips explicit option labels without mistaking `1.5` for label `1`;
- preserves significant operators in unsupported numeric expressions instead
  of claiming symbolic or unit-conversion equivalence;
- retains the stable material-duplicate rejection code in both validation
  layers, including inventory quarantine diagnostics;
- prevents a proof explanation's conclusion from silently losing its minus
  sign, and recognizes a Unicode minus in the existing option-pattern check.

Comparison uses bounded literals and exact rational arithmetic, not `eval`,
float tolerances, arbitrary expression execution or a model's claimed answer.
Empty/punctuation-only options, actual duplicate values, unsupported proof
families and independent verification failures remain rejected. All four
choices and the declared answer still pass the existing verification pipeline.

Question-stem normalization, persisted question/content/claim hashes, migration
sources, public answer boundaries, proof versions and retry limits are unchanged.
This backend-only release retains the 8.7.16-ui1 frontend caches intentionally.
Saved-pack reads keep their existing checksum/source/verification boundaries and
check literal option uniqueness without imposing newer generation heuristics.
Real-checksum round-trip tests cover both new numeric choices and a legacy pack
that the older equivalent-value check could certify; changed content still
fails its original checksum. No legacy answer or pack is rewritten.

## Live evidence and limits

Read-only checks on 20 September IST found 12/13 posted on each of 17–19
September. The retained dead letters were Current Affairs (source diversity,
duplicates), Mathematics (duplicate options, provider/verification failures)
and Reasoning (duplicates, topic diversity, Bengali text). No historical job
was replayed, reset, force-posted or removed.

Those failure codes motivated the investigation. Rejected source payloads were
not retained as evidence here, so this does **not** establish that every live
duplicate rejection was false, explain every missed quiz, or prove improved
production yield. Source breadth, valid reserves and independent verification
remain required. Native Telegram/Bengali assistive-technology QA is separate.

## Release and rollback

Local verification on 20 September: 1,133 Python tests passed and 62 were
skipped (database-dependent checks require protected CI); the focused numeric,
pack-read, inventory and identity suite passed 292 cases. Ruff, mypy across
92 source files, the 65 historical migration pins and `git diff --check` passed.
Protected CI and exact staging checks remain required; these local results are
not production deployment evidence.

Require full Python/database, static, mobile/security CI and exact staging
learner-flow checks before promotion. No database migration is introduced.
After the prerequisite release is actually promoted, record its exact production
commit as the application rollback target. Do not invent a future rollback SHA
or invalidate existing immutable packs to apply this validator correction.
