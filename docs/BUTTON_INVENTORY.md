# Interactive-control inventory

This inventory is the manual and automated UI test matrix. “API/action” names the
intended behaviour; “release checks” must all pass before the control is signed
off. All user-facing failures must use clear Bengali text.

Common release checks for every control: one action per activation, visible
loading state for network work, disabled state while pending, visible recovery
after failure, at least a 44×44 CSS-pixel touch target where practical, visible
keyboard focus, and no unintended loss of quiz/revision progress.

The automated frontend contract test checks that every static button is wired to
a click/form handler, every static link has a safe destination, practice failures
stay inline, and the filter/pagination controls retain their loading and disabled
states. This is not a substitute for the small-device Telegram sign-off below.

## Quiz page (`/`)

| Control | API or action | Release checks |
|---|---|---|
| Start/open quiz | `GET /api/quiz/{quiz_id}` | Skeleton, unavailable/expired state, answers absent |
| Previous question | Local saved attempt state | First item disabled, selection preserved |
| Next question | Local saved attempt state | Last item becomes review/submit action |
| Question-number navigation | Local saved attempt state | Current/unanswered states announced |
| Choose answer | Local saved attempt state | Large target, no correct-answer reveal |
| Submit quiz | `POST /api/quiz/{quiz_id}/submit` | Confirmation, UUID reuse, double-click blocked |
| Retry submission | Same request and attempt UUID | Returns original result, never duplicates |
| View result | Result state or persisted attempt | Refresh-safe, server score only |
| View explanation | Post-submission result data | Hidden before submission, readable Bengali |
| View source | Validated external URL | Safe scheme, new-context warning/label |
| Bookmark/add | `POST /api/me/bookmarks` | Signed ownership, optimistic state reconciled |
| Remove bookmark | `POST /api/me/bookmarks` with `active: false` | Idempotent, recovery copy |
| Report question | `POST /api/questions/{question_id}/report` | Reason validation, duplicate click blocked |
| View leaderboard | Quiz dashboard route | Signed user highlighted or login guidance |
| Open personal dashboard | `/dashboard` | Telegram navigation works |
| Retake/practice | New attempt UUID, practice-labelled | Cannot alter official first-attempt rank |
| Back/Telegram return | Telegram BackButton/history | Warn only when unsaved progress exists |

## Quiz dashboard/result

| Control | API or action | Release checks |
|---|---|---|
| Quiz leaderboard | User-aware quiz ranking endpoint | Top ten plus current row when outside list |
| Your-rank summary | Server ranking projection | Rank, score, accuracy, correct/incorrect/unanswered, time, percentile, movement |
| Result question row | Expand review details | Correct/incorrect/unanswered accessible labels |
| Topic mistake link | Filter review/revision queue | Filter is visible and reversible |
| Start recommended revision | Explicit revision-mode queue | Server-provided mode, due items only |
| Report from review | Question report endpoint | Same ownership/rate-limit rules as quiz page |
| Source from review | Validated source URL | Never render unsafe URL/HTML |

## Personal dashboard (`/dashboard`)

| Control | API or action | Release checks |
|---|---|---|
| Refresh dashboard | `GET /api/me/dashboard` | Identity retained, stale values not mixed |
| Start revision | `GET /api/me/reviews/due` | Due/overdue counts match queue |
| Revise weak questions | `GET /api/me/wrong-questions` | Explicit revision mode |
| Subject filter | Client/server filter | Empty state and reset available |
| Chapter filter | Client/server filter | Valid options follow subject |
| Date filter | Dashboard query/filter | Time zone is Asia/Kolkata |
| Reset performance filters | Client-side reset | Restores all subjects, all chapters, and 30 days |
| Weekly ranking tab | User-aware weekly endpoint | Current row always discoverable |
| All-time ranking tab | User-aware overall endpoint | Deterministic calculation text available |
| Recent quiz | Open quiz result dashboard | Quiz and overall dashboard wording distinct |
| Bookmark list/item | Bookmark queue/detail | Removed or quarantined item handled safely |
| Sound toggle | Preference endpoint + local fallback | Persists, labelled on/off, no autoplay attempt |
| Test sound | Local Web Audio action | User gesture only, moderate volume |
| Vibration toggle | Preference endpoint | Capability-safe and independent from sound |
| Automatic Telegram theme | Telegram theme variables | Contrast updates without a dead control |
| Mobile navigation | Route/state change | No overflow; active item announced |
| Leaderboard previous/next | `limit`/`offset` leaderboard query | 20-row pages, duplicate clicks blocked, end state visible |

## Revision/practice page (`/practice`)

| Control | API or action | Release checks |
|---|---|---|
| Start due revision | Due queue endpoint | Response contains `mode: revision` |
| Start weak revision | Wrong queue endpoint | Response contains `mode: revision` |
| Start practice | Practice queue endpoint | Response contains `mode: practice` |
| Choose/check answer | Idempotent practice-answer endpoint | One request, immediate visual result |
| Mistake sound | Local user-gesture-unlocked audio | Wrong revision only and exactly once |
| Next question | Local queue progression | Current result saved before advance |
| Previous/review | Local safe navigation where enabled | No duplicate answer submission |
| Explanation | Checked-answer payload | Visible after check only |
| Source | Checked-answer payload | Safe link and provenance label |
| Bookmark | Bookmark endpoint | Loading/error state |
| Report | `POST /api/me/practice/{question_id}/report` | Attempt-owned loading/error/success state |
| Finish revision | Summary + dashboard refresh | Counts and schedule are committed |
| Retry failed answer | Same answer attempt UUID | Original result returned |
| Empty-state action | Return/dashboard or change queue | No dead button |
| Inline submission error | Retry the same frozen answer | No blocking alert; duplicate attempt is not created |

## Telegram and operational controls

| Control | API or action | Release checks |
|---|---|---|
| Telegram Mini App open button | Public quiz URL with signed context | Invalid/expired auth handled safely |
| Telegram return/open button | Telegram API or safe `https://t.me/` link | Browser fallback works |
| Manual generation workflow | Guarded GitHub workflow dispatch | Stage/prod separation and logical date shown |
| Manual rerun | Same subject/logical-date lock | No duplicate quiz or Telegram post |
| Render health check | `/health/ready` | HTTP 503 on essential dependency failure |

## Sign-off evidence

For each page, retain test output plus screenshots at 320 px, 360 px, and 412 px
width. Manual Telegram checks must record Android/iOS/browser, quiz ID, attempt ID,
logical date, and whether the account was inside or outside the visible top ten.
Never record signed `initData` or any secret in the evidence.

The local cloud-browser runner cannot reach the workspace loopback server, so no
manual device row is signed off by the repository tests. Capture those screenshots
against the private staging URL after staging is active.
