# Telegram Mini App reliability and UX plan — 2026-08-31

## Scope

This document audits the learner-facing problems supplied in the 31 August
prompt and screenshots. It is an implementation plan, not an implementation.
No production Supabase, Render, Telegram, GitHub, or DNS state was changed.

The supplied text attachment ends during the settings-page section at “But
decide the best implementation”. Every available line and every attached
screenshot was included; no missing continuation was invented.

The untracked workspace path `20` was preserved and not inspected.

## Executive outcome

The first-load failures have one reproduced primary mechanism:

1. Production is on Render's free plan and can sleep.
2. A read-only production check observed the first `/health/live` response take
   **23.485 seconds**.
3. `service-worker.js` aborts every intercepted API GET after **8 seconds**.
4. `index.js` independently aborts quiz reads after **8 seconds**.
5. The otherwise shared helper allows 15 seconds for GETs, but the service
   worker's shorter deadline wins in production.
6. The quiz catch handler displays the abort exception's raw `message`.

This explains the reported sequence precisely: the first request is aborted
while Render wakes, a later retry reaches the now-warm service, and the learner
sees `signal is aborted without reason` instead of a safe Bengali state.

The dashboard and practice screens are affected by the same service-worker
deadline. Their code hides the raw exception, but incorrectly describes every
failure as an internet or Telegram-launch problem.

The existing test suite passes because its browser server is HTTP, while the
application only registers the service worker on HTTPS. The production-only
8-second interception path is therefore absent from the current browser tests.

## Evidence snapshot

- Repository branch: `main` at `0aa5ef2b8c244c56e18a76ca1ae27727eb9cf446`.
- Production application code: `6c4505bab11e6f694b4920e789b5d5e79e180173`.
- Application code after the deployed commit is unchanged; later local commits
  are operational documentation.
- Render blueprint: free plan, one Uvicorn process, Singapore.
- Production timing sampled read-only on 31 August 2026:

| Request order | Endpoint | HTTP | Time to first byte |
|---|---|---:|---:|
| 1 | `/health/live` | 200 | 23.485 s |
| 2 | `/health/ready` | 200 | 5.480 s |
| 3 | `/api/quizzes/recent?limit=5` | 200 | 0.562 s |
| 4 | `/api/quiz/20260830-current-affairs` | 200 | 0.922 s |

The first slow response followed by fast warm responses confirms a live cold
start. It does not prove that every historical screenshot had only this cause;
the old dashboard RPC defect described below also existed when some screenshots
were taken.

## Findings and classification

`CONFIRMED` means current code or live read-only behavior reproduces the
condition. `LIKELY` means the code creates a credible latency/failure amplifier
but needs timings to assign its exact share. `POSSIBLE` means it is worth
instrumenting, not changing speculatively. `NOT RELATED` rules out a suggested
cause for this path.

| ID | Classification | Finding | Evidence and consequence |
|---|---|---|---|
| R-01 | **CONFIRMED** | Competing API timeouts | Shared GET deadline is 15 s; the service worker and quiz page each impose 8 s. The shortest layer wins. |
| R-02 | **CONFIRMED** | Render cold start exceeds the client deadline | The first live response took 23.485 s on the configured free service. |
| R-03 | **CONFIRMED** | Raw abort text is rendered | `index.js` passes `err.message` directly to the quiz error UI. |
| R-04 | **CONFIRMED** | No central frontend error taxonomy | Pages duplicate response parsing and reduce different failures to unrelated generic copy. |
| R-05 | **CONFIRMED** | Safe automatic read retry is absent | Initial GETs have manual retry buttons but no bounded policy for network/timeout/502/503/504. |
| R-06 | **CONFIRMED** | Dashboard copy falsely blames internet | All `/api/me/dashboard` failures use one internet message, including 401, 429, 503, timeout, and invalid responses. |
| R-07 | **CONFIRMED** | Practice copy falsely blames Telegram launch | Missing auth, expired auth, offline, timeout, rate limit, server failure, and invalid queue contracts all reach one state. |
| R-08 | **CONFIRMED** | Failed practice load resembles a valid zero | The header starts at `০টি` and changes only after success. It remains zero on failure. |
| R-09 | **CONFIRMED** | Dashboard does three serial database operations | Each read upserts the user, calls the dashboard RPC, then calls preferences to build the study plan. |
| R-10 | **CONFIRMED** | Practice duplicates authenticated database work | Queue and preferences requests run together, but each independently upserts the same user. The UI still waits for the optional preference request to finish or time out. |
| R-11 | **CONFIRMED** | Database and whole-request budgets are misaligned | The database client allows 8 s per operation while the production service-worker gives the entire HTTP request only 8 s. |
| R-12 | **LIKELY** | Full quiz projection work amplifies tail latency | Public quiz loading reads run metadata, the question pack, and validates the pack/checksum before returning or attempting fallback. Instrument before optimizing. |
| R-13 | **LIKELY** | Dashboard query/upsert amplification worsens tails | Serial remote calls and unconditional `last_active` writes increase failure opportunities. Measure each hop before changing query behavior. |
| R-14 | **CONFIRMED** | There is no request correlation or stage timing | Responses and logs do not expose a safe request ID, total duration, or per-database-stage timing. |
| R-15 | **NOT RELATED** | Supabase Auth | This learner path verifies Telegram HMAC locally and uses service-role database calls; Supabase Auth is not in the request chain. |
| R-16 | **NOT RELATED** | Backend emitting the abort literal | The abort wording is a browser exception exposed by frontend code, not a backend response. |

### Historical defects that must not be reimplemented

- The earlier dashboard RPC declared a writing projection `STABLE`, causing
  PostgREST read-only transaction failures (`SQLSTATE 25006`). Migration
  `20260829031810_dashboard_rpc_transaction_mode.sql` correctly changed it to
  `VOLATILE`.
- The earlier bookmark question-identity projection was repaired by migration
  `20260829091919_bookmark_question_identity_projection.sql`.
- The Citizen Affairs parent-site CTA already exists on the quiz introduction
  before Start and has campaign parameters. Preserve it.
- Telegram HMAC validation, write idempotency, answer-free cache boundaries,
  immutable quiz checksums, and service-role-only learner RPCs are existing
  safety controls. Reliability changes must not weaken them.

## UX/UI findings

| ID | Classification | Finding | Product impact |
|---|---|---|---|
| U-01 | **CONFIRMED** | The permanent 5×2 question map dominates short screens | Touch targets are large enough, but navigation takes priority over the question. |
| U-02 | **CONFIRMED** | Telegram MainButton and the fixed five-item app nav coexist | Two bottom action layers consume space and create accidental-exit risk during an assessment. |
| U-03 | **CONFIRMED** | Affected pages do not use Telegram safe/content insets or stable viewport height | Static bottom offsets can clip or crowd controls across Android/iOS Telegram versions. |
| U-04 | **CONFIRMED** | Practice has only loading/empty/error/question states | Timeout, offline, auth, rate-limit, server, and completed states cannot be communicated truthfully. |
| U-05 | **CONFIRMED** | Practice Submit looks enabled before an option is selected | Tapping it silently does nothing, which feels broken. |
| U-06 | **CONFIRMED** | Practice completion reuses the empty state | “Nothing was available” and “you completed the queue” are different outcomes and need different summaries/actions. |
| U-07 | **CONFIRMED** | Feedback and Next compete with a fixed global nav | The cramped bottom region in the screenshots follows from normal-flow actions plus fixed navigation. |
| U-08 | **CONFIRMED** | Settings puts exams before subjects | This contradicts the product rule that subjects are primary and target exams are secondary/optional. |
| U-09 | **CONFIRMED** | All 24 subject/exam choices are expanded at once | The wrapping pill wall is tall, visually noisy, and hard to scan. |
| U-10 | **CONFIRMED** | Account actions lack hierarchy | Export, cancel deletion, and destructive deletion look equivalent. |
| U-11 | **CONFIRMED** | Study-plan fallback prioritizes an exam mock before a preferred-subject quiz | When due/weak work is clear and the daily goal remains, saved target exams win over saved subjects. |
| U-12 | **CONFIRMED** | Branding is only partial | The palette and intro CTA exist, but MainButton uses hard-coded teal/blue, learner screens lack a consistent wordmark, and page tokens/radii differ. |
| U-13 | **CONFIRMED** | Several states are visual-only | Options lack `aria-pressed`, the current question lacks `aria-current="step"`, most active tabs lack `aria-current="page"`, and nav labels shrink to 9 px. |
| U-14 | **CONFIRMED** | English content is not marked with element-level language | A Bengali document can contain English questions, but assistive technology needs `lang="en"` on that content. |
| U-15 | **NOT RELATED** | Telegram's native top bar | Close/back, host title, menu, and status bar belong to Telegram. BotFather/configuration controls branding there, not repository CSS. |

## Target experience

### Navigation and bottom-action policy

Only one primary bottom action surface may be active at a time.

| Screen state | Telegram Mini App | Browser/PWA |
|---|---|---|
| Home, dashboard, settings, non-blocking result | Global app navigation | Global app navigation |
| Quiz intro and resources | Telegram MainButton; app nav hidden/inert | In-page primary action; app nav visible |
| Active quiz | Telegram MainButton + BackButton; app nav hidden/inert | Assessment action footer; app nav hidden |
| Active practice/revision and feedback | Telegram MainButton; app nav hidden/inert | Assessment action footer; app nav hidden |
| Modal or bottom sheet | Underlying actions hidden/inert | Underlying actions hidden/inert |
| Blocking error or empty state | One contextual action, then global nav | One contextual action, then global nav |

Use a body-level screen-state attribute/class as the single source for action
visibility. Do not independently show/hide controls in multiple page branches.

The longer-term information architecture should use four top-level destinations:

1. `কুইজ` — home, daily quizzes, and mock discovery;
2. `অনুশীলন` — segmented Due, Wrong, Bookmarks, and Weak Topics;
3. `অগ্রগতি` — dashboard, syllabus, and rankings;
4. `সেটিংস`.

Combining Wrong Practice and Revision under one preparation destination removes
the current five-label squeeze without removing either learning workflow.

### Shared safe-area shell

Extend the existing vanilla shell; do not introduce a frontend framework.

- Synchronize Telegram `safeAreaInset`, `contentSafeAreaInset`,
  `viewportHeight`, and `viewportStableHeight` into CSS variables.
- Listen for Telegram viewport, safe-area, content-safe-area, and theme changes.
- Use `env(safe-area-inset-*)` and `100dvh` as browser fallbacks.
- Define one `--bottom-ui-height` and derive page padding/action position from it.
- Centralize bottom nav, state card, button, surface, spacing, typography, focus,
  and dark-theme primitives in the shared shell.
- Never reduce navigation labels below 11 px; allow wrapping or shorten labels.

### Quiz screen

Replace the always-visible 5×2 map with a compact summary control:

> প্রশ্ন ১ / ১০ · উত্তর ৩ · চিহ্নিত ১ 〉

Tapping it opens an accessible bottom sheet containing the existing ten 44 px
question buttons, a state legend, one-tap navigation, focus trapping, Escape/
Back handling, and focus return. The functionality remains; persistent height
is reclaimed for the question.

Additional changes:

- Compact subject/chapter, timer, position, and progress into one assessment
  header.
- Replace the technical quiz-ID pill with learner-facing date/subject; retain ID
  only in diagnostics.
- Add non-color selected/answered/marked/current indicators.
- Add `aria-pressed` to answer options and `aria-current="step"` to the current
  question.
- Move focus to the new question heading after navigation.
- Mark English question/option nodes with `lang="en"` when appropriate.
- Use one calculated action color for HTML and Telegram controls; remove the
  hard-coded teal and result blue.
- Keep the Citizen Affairs CTA before Start, visually secondary to the quiz
  action and clearly marked as an external link.

### Practice and revision

The count must be `—` until a queue request succeeds. `০` is legal only after a
successful empty response.

Use these distinct states:

| State | Header count | Learner copy/action |
|---|---|---|
| Loading | `—` | Skeleton plus “প্রশ্ন লোড হচ্ছে…” |
| Slow/cold start | `—` | “সার্ভার প্রস্তুত হচ্ছে—আর কয়েক সেকেন্ড সময় লাগতে পারে।” |
| Loaded | Actual | Show current question and progress |
| Successful empty | `০` | Source-specific positive explanation and next study action |
| Completed | Reviewed count | Completion summary, outcome, Dashboard/Next Study |
| Offline | `—` | Confirm connection is absent; retry when online |
| Timeout | `—` | Explain that the response is taking longer; safe retry |
| Auth required/expired | `—` | Reopen from the bot/Mini App CTA |
| Rate limited | `—` | Cooldown copy, use `Retry-After` when present |
| Temporary server failure | `—` | Temporary-service copy and retry |
| Unknown | `—` | Safe generic copy and request ID; no exception text |

Behavior changes:

- Submit starts disabled and enables only after a choice.
- On an uncertain write, freeze the answer and retry with the same attempt UUID.
- After success, focus the feedback heading and announce correct/wrong without
  relying on color.
- Keep explanation/source visible, but leave reporting collapsed.
- Position Next above the calculated safe area and only after feedback.

### Settings

Reorder and compact the learning section:

1. `পছন্দের বিষয়` — first and primary; summary such as “৮টি নির্বাচিত”.
2. Daily question goal.
3. Quiz mode and difficulty.
4. `লক্ষ্য পরীক্ষা (ঐচ্ছিক)` — secondary; explain that it refines mock/syllabus
   recommendations and does not replace the subject-based quiz catalogue.

The subject and exam rows open accessible native `<dialog>` selectors styled as
mobile bottom sheets. Each selector needs a title, selected count, searchable or
two-column 44 px choice list, Clear, Done, a temporary draft until Done, focus
trap, Back/Escape handling, backdrop close, and focus return.

- Keep privacy/ranking as a separate compact section.
- Move destructive deletion into a collapsed `অ্যাকাউন্ট ও ডেটা` danger zone.
- Style Export normally and Delete destructively with two-step confirmation.
- Render Privacy and Terms as full-width destination rows.
- Enable Save only when dirty; expose pending/success/failure and warn before
  discarding unsaved changes.

### Subject-first recommendation policy

Preserve this priority:

1. due revision;
2. weak-topic remediation;
3. goal-complete state;
4. preferred-subject quiz;
5. optional target-exam mock;
6. broad maintenance.

Target exams may filter or recommend mock/syllabus content, but must not replace
subject-first learning. Broadcast daily quizzes remain non-personalized.

### Brand system

Use stable Citizen Affairs identity tokens separately from Telegram action
tokens:

```css
--brand-primary: #b42318;
--brand-primary-strong: #8f1c13;
--brand-link: #0a5aa6;
--brand-canvas: #f7f7f6;
--brand-ink: #222222;
--action-primary: var(--tg-theme-button-color, var(--brand-primary));
```

- Use one text wordmark, `CITIZEN AFFAIRS বাংলা`, plus the current page title on
  all learner screens.
- Use brand red for identity/editorial accents and Telegram action color for
  native-action harmony.
- Standardize radius, spacing, elevation, and state colors.
- Do not invent a logo; no approved logo asset exists in the repository.

## Reliability implementation plan

### Phase A — failing regressions first

Add tests that fail on the current implementation:

- 24-second delayed initial quiz read succeeds without a raw error.
- Service worker and page client do not create competing deadlines.
- 401/403/404/409/429/500/502/503/504, offline, network failure, and timeout map
  to the expected typed state.
- Safe GET retries occur only for network/timeout/502/503/504 and are bounded.
- 400/401/403/404 and validation/conflict responses are not automatically
  retried.
- Writes are never automatically retried unless their endpoint explicitly
  declares replay-safe idempotency.
- Failed practice reads never display zero or an empty-state success.
- Production-like HTTPS tests activate and control the service worker.

### Phase B — one HTTP owner

Make `miniapp-shell.js` the only frontend HTTP client.

- Remove the private `index.js` fetch helper.
- Return a typed `MiniAppRequestError` with category, HTTP status, retryability,
  request ID, and safe context; never use the raw message as learner copy.
- Compose caller cancellation and timeout cancellation without losing the
  category.
- Use a cold-start-tolerant read budget and progressive loading copy rather than
  aborting at eight seconds.
- Apply at most one bounded GET retry with jitter for network/timeout/
  502/503/504. Respect `Retry-After` for 429 but do not spin automatically.
- Let each write opt into retry only after its idempotency contract is tested.
- Replace duplicated `check`/`jsonOrThrow` helpers across learner pages.

### Phase C — service-worker ownership

- Stop intercepting sensitive API reads merely to add a shorter timeout; let
  the page client own API cancellation and classification.
- Keep answer-free network-first caching and stale fallback, but make its
  network deadline consistent with the shared policy.
- Preserve the rule that answers, attempts, auth data, rankings, and learner
  projections are never cached.
- Version the caches and test old-worker activation/update behavior.

### Phase D — truthful page states

Adopt one state renderer and Bengali copy catalogue on quiz, home, dashboard,
practice, settings, mock, syllabus, and admin surfaces. Never say “check your
internet” unless offline/network failure was actually detected. Never say
“open from Telegram” for a server timeout.

Internal categories:

- `AUTH_REQUIRED`
- `AUTH_EXPIRED`
- `OFFLINE`
- `NETWORK_FAILURE`
- `REQUEST_TIMEOUT`
- `SERVER_TEMPORARY`
- `RATE_LIMITED`
- `NOT_FOUND`
- `INVALID_REQUEST`
- `CONFLICT`
- `UNKNOWN`

### Phase E — backend observability and latency

- Add/validate an `X-Request-ID` for every request and return it in the response.
- Log safe structured fields: request ID, route template, method, status, total
  duration, database operation label/duration, and error category. Never log
  Telegram init data, tokens, keys, answers, or private learner payloads.
- Add `Server-Timing` in non-sensitive form for diagnostics.
- Establish cold/warm and authenticated route percentiles before query changes.
- Consolidate dashboard plus preferences into one database round trip.
- Return practice queue plus the preferences needed for presentation in one
  bootstrap contract, or perform preference ordering server-side.
- Replace unconditional read-time `last_active` writes with a measured,
  throttled touch policy without weakening identity updates.
- Measure quiz projection stages and dashboard queries with `EXPLAIN (ANALYZE,
  BUFFERS)` in staging before adding indexes or caches.
- Align database per-operation and HTTP end-to-end budgets deliberately.

### Phase F — hosting decision

The code changes above make a free cold start survivable, not world-class. An
always-on service is the only direct way to remove platform sleep latency. Keep
the current free plan for now as requested; use the new telemetry to decide when
an always-on Render plan or another approved always-on runtime becomes a release
gate. Do not add fake keep-alive traffic as a substitute for an uptime contract.

## UX implementation plan

After reliability Phase D is stable:

1. Build the shared safe-area shell and single-action-surface policy.
2. Redesign quiz navigation and active assessment layout.
3. Implement the practice/revision state machine and action flow.
4. Redesign settings selectors, subject hierarchy, account danger zone, and
   dirty-save behavior.
5. Change the study-plan fallback to preferred subject before optional exam.
6. Apply the shared Citizen Affairs wordmark/tokens and accessibility semantics.
7. Run the full production-like mobile/Telegram regression matrix.

This order prevents polished screens from being built on top of the current
broken request/state model.

## Primary files expected to change

- Shared networking/shell: `miniapp-shell.js`, `miniapp-shell.css`,
  `service-worker.js`.
- Quiz: `index.html`, `index.css`, `index.js`.
- Practice: `practice.html`, `practice.css`, `practice.js`.
- Dashboard: `dashboard.html`, `dashboard.css`, `dashboard.js`.
- Settings: `settings.html`, `settings.css`, `settings.js`.
- Other consumers: `mock.js`, `syllabus.js`, `admin.js` and their state markup.
- Backend: `app.py`, learner route/service/repositories, configuration, and one
  additive Supabase migration if the combined RPC contracts are selected.
- Tests: frontend contract tests, service-worker tests, API/service tests, and
  Playwright home/quiz/practice/dashboard/settings/mobile/accessibility specs.

## Acceptance gates

### Reliability

- A 24-second cold initial read reaches success without a raw exception.
- No learner-visible string contains `AbortError`, `signal`, `fetch`, RPC names,
  stack text, or database errors.
- Only safe reads use the documented bounded retry policy.
- Idempotent quiz/practice writes retain the same client attempt ID on retry.
- Failure never renders a successful zero/empty state.
- Every production error can be correlated by request ID without exposing
  private data.
- HTTPS browser tests execute the service-worker path.

### Mobile UX

- Exactly one bottom action surface is visible in every state.
- The current/next action remains visible at 320×568, simulated bottom inset
  34 px, keyboard open/closed, and 200% text.
- The compact question summary and question-map sheet are keyboard- and
  screen-reader-operable.
- Submit is disabled until selection; uncertain writes preserve the answer and
  attempt ID.
- Empty, completed, offline, timeout, auth, rate-limit, and server states are
  visually and semantically distinct.
- Subject selection precedes optional exam selection in UI and recommendation
  tests.
- Active quiz, practice feedback, error/empty/completed states, and settings
  dialogs have automated WCAG 2.2 AA checks and visual snapshots.
- A real Telegram staging matrix verifies Android and iOS MainButton,
  BackButton, theme, viewport, and safe-area behavior before production release.

## Baseline verification

- Targeted Python/static contract suite: **78 passed**, one existing Starlette/
  httpx compatibility deprecation warning.
- Targeted Playwright run at 360×800: **13 passed**.
- These green results confirm the current baseline remains intact; they do not
  contradict the audit because the existing tests omit HTTPS service-worker
  timing and most error-state matrices.

## Implementation checkpoint — 2026-09-01

Reliability phases A–D and the shared safe-area/action-surface foundations are
implemented. The production-like HTTPS suite now exercises the service worker,
including a 24-second cold quiz read, typed error handling and cache ownership.
Quiz, practice, settings and learner-shell changes described above are covered
across the four supported Android viewport widths.

The timed-mock follow-up now:

- hides global navigation during an active assessment;
- replaces the permanently expanded palette with a compact answered/marked
  summary and an on-demand 44 px question map;
- gives current, answered and marked items visible and semantic states;
- moves focus to the question heading after question/section navigation;
- exposes the Citizen Affairs parent-site CTA before Start;
- shows the next-section action only after the final question in the current
  section; and
- aligns mock and syllabus navigation with the four-destination shell.

Verification at this checkpoint: 256 Playwright mobile tests, six HTTPS
service-worker tests, 50 focused Python contract tests, Ruff, mypy, JavaScript
syntax validation and npm audit all pass. The real Telegram Android/iOS and
assistive-technology matrix remains a manual release-signoff item; this entry
does not claim that external validation is complete.

## Decisions intentionally deferred

- No production mutation or deployment is part of this audit.
- No Render upgrade is included in the current plan execution unless the owner
  later approves it.
- No frontend framework rewrite is justified.
- No speculative database index will be added before stage timings and a
  staging query plan identify the bottleneck.
- Telegram's native top-bar branding needs BotFather/Telegram configuration and
  is separate from the web UI implementation.
