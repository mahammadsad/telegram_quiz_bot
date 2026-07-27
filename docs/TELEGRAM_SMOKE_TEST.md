# Private Telegram smoke-test guide

Use only the configured private staging destination and a disposable staging
learner. Do not record bot tokens, topic IDs, signed `initData`, answer keys, or
private user identifiers in evidence.

## Delivery and Mini App

- Preflight succeeds without posting or consuming generation quota.
- One selected source-covered subject generates one certified ten-question pack.
- Exactly one message appears in the intended forum topic.
- The deep link contains the expected quiz start parameter and opens the
  staging HTTPS Mini App URL.
- A valid Telegram launch authenticates; an invalid signature and an expired
  payload each receive 401 without database writes.
- Retrying the worker reuses the saved certified pack and does not post again.

## Learner lifecycle

Use a fresh client attempt UUID for the first submission and retain it only in
the private test session:

1. Complete the first attempt and confirm one result.
2. Double-click submit; only one request may be active and only one attempt row
   may exist.
3. Simulate a lost response, retry with the same UUID, and recover the identical
   result without another row.
4. Refresh during submission and recover using the same UUID.
5. Refresh the result and load the owned result-recovery route.
6. Choose retake and confirm a new UUID and a second attempt.
7. Confirm the private rank card and highlighted current-user row, including
   when outside the first ten public rows.
8. Report one owned question; reject a duplicate or unowned report.
9. Add and remove a bookmark, then load the wrong-question practice queue.
10. Submit an incorrect revision. Show answer, explanation, source, and next
    review only after the authenticated POST.
11. With sound enabled, play one mistake sound for the incorrect revision.
    Confirm no sound during the first quiz attempt, ordinary practice, a correct
    revision, refresh, or result recovery.
12. Verify `posting_unknown` is never automatically retried. Inspect the private
    topic before an explicitly acknowledged manual recovery, and confirm no
    duplicate message.

## Evidence record

Record UTC/IST timestamps, quiz ID, workflow/run link, HTTP status codes, row
count deltas, boolean checks, and sanitized screenshots. Do not copy response
bodies that contain review answers, explanations, source excerpts, signed
launch data, or private Telegram fields.

The lifecycle passes only when delivery count is one, first-attempt retry is
idempotent, retake creates a new UUID, recovery works, pre-submission data is
answer-free, revision scheduling advances, and private ownership checks reject
the invalid/expired/unowned cases.
