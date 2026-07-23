# Statistics and ranking rules

These rules are implemented in PostgreSQL and are the source of truth for the
values shown by FastAPI and the Mini App. Dates and activity windows use
`Asia/Kolkata`.

## Quiz result (one ten-question quiz)

| Value | Rule |
|---|---|
| Score / correct | Number of saved question versions answered correctly, from server-side scoring |
| Incorrect | Answered questions minus correct questions |
| Unanswered | Ten minus answered questions |
| Accuracy | `score / 10 × 100`, rounded to two decimals |
| Time | Client duration accepted only within the API bounds; null sorts after known times |
| Official quiz attempt | The first completed attempt for that user and quiz |
| Retake | A completed attempt with a new UUID and `attempt_number > 1` |

The official quiz rank is deterministic: higher score, then more answered
questions, then lower duration, then earlier completion, then immutable attempt
ID. A retry with the same client UUID returns the original result and is not a
new attempt. Retakes and personal practice never alter this rank.

Percentile is `100 × (participants - rank) / (participants - 1)`. A sole
participant receives 100. The last-ranked participant receives 0.

## Personal dashboard

The learning dashboard is intentionally broader than a competitive rank:

- total answered, correct, accuracy, response time, activity, subject/chapter
  performance, and streaks include completed quiz answers and checked personal
  practice/revision answers;
- unanswered quiz positions are not counted as answered;
- total quizzes completed counts distinct completed quiz IDs, so retaking one
  quiz does not increase that value;
- strongest and weakest subjects require answered data and order by accuracy,
  then attempt volume, then stable subject key;
- weak/strong micro-topics require at least two answered events;
- current streak is the consecutive activity-day island ending today or
  yesterday; best streak is the longest recorded island;
- revision completion is mastered scheduled questions divided by all scheduled
  questions;
- due today means `next_review = current_date`; overdue means an earlier date;
  both use the Kolkata logical date.

## Competitive typed leaderboards

Overall rank, daily, weekly, monthly, and subject accuracy use only answered
questions from completed first quiz attempts. Personal practice, revision,
abandoned attempts, idempotent retries, invalid attempts, and retakes are
excluded. Overall rank sorts by total correct, then accuracy, answered volume,
earlier last activity, and stable user ID.

Minimum participation is five answers for the daily board and ten answers for
the other accuracy boards. Accuracy boards sort by accuracy, answered count,
total answer count, earlier last activity, then stable user ID.

The specialized boards are labelled separately:

- improvement compares a quiz's first completed attempt with its latest retake;
- consistency counts official first-attempt activity days in the last 30 days,
  then accuracy and volume;
- revision completion ranks mastered scheduled questions divided by all
  scheduled questions.

The current user may see their own row even when outside the visible top list.
Users who opt out are omitted from public rows but may still see their private
row. Public rows never expose Telegram IDs; usernames appear only after opt-in.

## Revision schedule

Every user-question schedule records first and last attempt, last revision,
attempt and revision counts, correct/incorrect counts, consecutive correct
revisions, interval, next date, ease, overdue flag, and learning stage.

An incorrect revision resets consecutive correct revisions and schedules one
day later. Correct revision intervals progress through 1, 3, 7, 14, 30, then 60
days; a slow or user-marked uncertain answer is scheduled sooner. A question is
mastered only after the required consecutive correct revisions. Quiz and
non-revision practice answers update learning evidence but do not masquerade as
a correct revision streak.
