# Non-programmer verification guide

Use staging first. Do not paste a password, API key, bot token, service key, or
Telegram signed data into screenshots or support messages.

## Before opening Telegram

1. In Supabase, confirm the selected project is
   `telegram-quiz-bot-rollout-staging`, not production or Citizen Affairs.
2. Ask the technical operator to show the `/health/ready` page. It must be HTTP
   200, say `ready`, show migration `20260724212939`, contract `2.2.0`, and every
   check must be true.
3. In GitHub Actions, confirm the Tests workflow is green and the manual
   preflight job succeeds before a subject job is run.

## Student journey

1. Open the staging quiz from the private Telegram topic. Confirm the subject,
   chapter, and ten questions are correct and no answer is revealed.
2. Select answers, move backward/forward, close once, and reopen. Progress should
   remain. Press submit twice quickly; only one result should appear.
3. Turn the network off during one staging submission, turn it back on, and use
   retry. The same result should return without a duplicate attempt.
4. Reload the result page once. The same signed-in user's result should return;
   choosing “পুনরায় পরীক্ষা” must start a genuinely new attempt.
5. Confirm score, correct/incorrect/unanswered, accuracy, time, and review cards.
   Sources must open an HTTPS page. Report one disposable staging question.
6. Open the quiz leaderboard. Your “আপনি” row and “আপনার র‍্যাঙ্ক” card must be
   obvious. If outside the top ten, your row must appear after a separator.
7. Open the personal dashboard. Your Telegram name/photo or initials and “এটি
   আপনার ড্যাশবোর্ড” must appear. Compare totals with the completed staging quiz.
8. Change the subject, chapter, and 7/14/30-day filters. Confirm each panel has a
   clear empty state, reset restores all results, and ranking pages move only once.
9. Start revision. A wrong answer must show both options, explanation, source,
   and play the sound once when enabled. A correct revision and every normal quiz
   answer must remain silent.
10. Turn revision sound off, reload, and verify it stays off. Test sound should
   run only after pressing its button. Repeat for optional vibration.
11. Test every row in `docs/BUTTON_INVENTORY.md` on a small Android device. Record
   only device type, quiz ID, expected action, and pass/fail—never signed data.

## Release decision

Do not approve production when readiness is 503, any checksum differs, a quiz
posts twice, an answer appears before submission, a retry creates another row,
the current user cannot be found, or revision sound plays in a normal quiz.
