# Release notes — 7.2.2 dedicated settings

Version 7.2.2 moves learner preferences and privacy controls out of the
statistics dashboard into a dedicated Bengali settings destination.

## Navigation and layout

- Quiz, Practice, Revision, Statistics, and Settings now share one consistent
  five-item mobile navigation.
- Settings has a dedicated gear icon and the page heading
  `পছন্দ ও গোপনীয়তা`.
- The Statistics dashboard no longer loads or renders preference controls.
- The 320 px to 412 px Android layouts keep accessible touch targets and reserve
  enough space below content for the fixed navigation.

## Preference behavior

- Existing learning goals, language, quiz mode, difficulty, target exams, and
  preferred subjects remain available.
- Existing leaderboard visibility, public display name, Telegram username,
  reminder, revision sound, and vibration controls retain the same private API
  and stored values.
- Sound and vibration choices continue to update the local revision fallback
  only after preferences are loaded or successfully saved.

## Deployment safety

- This release has no database migration and does not alter quiz, attempt,
  score, ranking, review, or preference records.
- The public-data scanner now treats `settings.html` as a required frontend
  asset and checks it for private server configuration names.
