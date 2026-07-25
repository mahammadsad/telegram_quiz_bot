# Mobile browser and screenshot evidence

The repository uses Playwright with deterministic API and Telegram Web App
mocks. Pull-request browser tests never depend on staging or production data.

Run:

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:browser
```

The required projects are `android-320x568`, `android-360x800`,
`android-390x844`, and `android-412x915`. CI uploads `playwright-report/` and
`test-results/` as the `mobile-browser-evidence-<attempt>` artifact for 30 days.

The suite attaches these evidence families at every viewport:

- intro, answered/marked navigation, submission loading, and result review;
- lost-response retry with the same attempt UUID;
- personal dashboard, current user outside the top ten, and empty states;
- incorrect revision/report, practice retry, and empty practice queue.

Interaction assertions additionally cover draft save/resume, refresh during
submission, result recovery, retake UUID rotation, answer visibility only after
submission, bookmarks, reports, revision-only sound, sound preference/test,
keyboard focus, reduced motion, Telegram MainButton/BackButton lifecycle,
horizontal overflow, fixed-navigation clearance, minimum touch targets, and
Bengali wrapping.

## Evidence rules

- Treat the HTML report as the source of the exact pass count and viewport list.
- Keep screenshot, trace, and video artifacts free of real Telegram launch data,
  tokens, keys, private topic IDs, and live learner details.
- A screenshot is supporting evidence, not a substitute for the associated
  interaction assertion.
- Do not mark the hosted Telegram/mobile gate complete from mocked CI alone.
  Record a separate sanitized real-device or Telegram staging observation.
