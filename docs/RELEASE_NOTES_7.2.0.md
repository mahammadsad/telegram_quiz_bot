# Release notes — 7.2.0 quiz quality and negative marking

Version 7.2.0 strengthens future source-backed quiz packs and introduces
exam-style marking without rewriting any historical quiz or attempt.

## Quiz diversity

- The grounding RPC now round-robins verified source documents across the
  active micro-topics of the selected approved chapter.
- Generation and independent verification receive the complete grounded topic
  set rather than one selected micro-topic.
- A ten-question pack must use up to four distinct verified sources and
  micro-topics, balanced as evenly as the available source set permits.
- Rephrased questions that reuse the same correct-answer relationship from the
  same source fact are rejected before persistence or Telegram posting.
- Exact, near-duplicate, immutable-version, source, checksum, difficulty, and
  answer-position safeguards remain active.

## Marking

- New quiz runs use `+1` for a correct answer, `-0.25` for a wrong answer, and
  `0` for an unanswered question.
- Historical quiz runs and attempts retain zero penalty and their previous
  ordering.
- The existing `score` field remains the raw number correct for compatibility
  and learning analytics. `netScore` is the quiz-ranking score.
- Official quiz ranking uses net score, then correct answers, fewer wrong
  answers, faster completion, and earlier completion.
- The Mini App shows the marking rule before the test, warns again before
  submission, and shows correct, wrong, deducted marks, and net score after
  submission.

## Safety

- Public quiz payloads remain answer-free and explanation-free.
- Marking policy is immutable after a quiz run is created.
- Attempt marking is captured transactionally and idempotent retries return the
  same result.
- The database contract fails closed unless diverse grounding, generated net
  scores, and both marking-policy triggers are present.
