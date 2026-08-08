# Release 7.6.0 — Phase D subject solver expansion

This staging-only release candidate expands deterministic mathematics,
reasoning, English, and Bengali verification without changing the database.

## What changed

- Mathematics now supports linear algebra, time-and-work, speed-distance,
  profit/loss, and explicit half-up rounding in addition to the existing
  arithmetic, percentage, average, ratio, and simple-interest families.
- Unit-bearing mathematics proves the expected unit and requires the same unit
  on all four answer choices.
- Mathematics and reasoning proofs now carry a machine-readable solution trace;
  any explanation trace that disagrees with the independent solver is rejected.
- Reasoning now supports Caesar-style coding shifts, cardinal direction paths,
  enumerated ordering constraints, finite-set syllogisms, and explicit analogy
  mappings in addition to the existing series, rank, and odd-one-out families.
- Under-constrained ordering puzzles are rejected when valid states do not
  prove a single rank.
- English and Bengali candidates use typed question forms and versioned
  authoritative rule artifacts with exact source spans.
- Bengali uncertainty is rejected with a stable human-review reason, and
  translation correctness requires a separate human-reviewed decision rather
  than being inferred from factual correctness or model confidence.
- A model-declared `human_reviewed` value is rejected unless a separate
  server-side operator attestation is attached.
- Every new inventory candidate now fails closed when its deterministic proof
  artifact is missing, including static and language subjects.

## Production safety

There is no database migration in this release. Production remains unchanged;
promotion still requires CI, mobile-browser, Render staging, and public
readiness evidence on the exact release commit.
