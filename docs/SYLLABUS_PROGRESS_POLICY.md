# Syllabus progress policy

The authenticated syllabus map reports evidence against active, reviewed
syllabus-v2 micro-topics. It is a transparent progress view, not a diagnostic
exam or proof that an entire exam syllabus has been learned.

## Units and denominator

- The evidence unit is an active `mapped` knowledge point attached to one of
  the 648 reviewed syllabus-v2 micro-topics.
- Legacy `:core`, unmapped, review-required, quarantined, and retired content is
  excluded from the mastery denominator.
- A knowledge point is attempted after one recorded quiz or practice outcome.
- A knowledge point is mastered only at mastery score 80 or above with at least
  two attempts, matching the existing strong-mastery rule.
- A micro-topic is labelled mastered only when every knowledge point currently
  mapped to it meets that rule. A micro-topic with no mapped knowledge points is
  labelled “content not mapped,” never complete.
- Coverage and mastery percentages use mapped knowledge points as their
  denominator. Content-mapped percentage separately shows how much of the
  reviewed syllabus has any assessable content.

The projection returns identifiers and aggregate counts only. It excludes
question text, claims, options, correct answers, learner identity, and attempt
history. It is authenticated, private, and `no-store`.

## Current limitation

The production read-only canary on 24 August 2026 found 1,362 active mapped
knowledge points attached to 288 of 648 reviewed micro-topics (44.4%). The UI
therefore distinguishes unprepared content and must not present the uncovered
55.6% as complete. Expanding verified content remains subject to the controlled
editorial and provenance gates.
