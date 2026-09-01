# Audit remediation status

Status as of 30 August 2026 for audit commit `cf51b4ebb9d4a3619968d39f710a616a91284181`.

Status meanings:

- **Implemented**: code and local automated evidence are complete; production impact still requires the release procedure.
- **Partial**: a material part is complete, but the full audit acceptance condition is not.
- **Awaiting external action**: credentials, production data, platform ownership, legal ownership, or a paid/reliable control plane is required.
- **Open**: not safely completed in this remediation branch.
- **No longer applicable**: current repository evidence disproves the finding or the condition was already fixed.

| ID | Severity | Current evidence | Status | Files / verification | Residual risk and external action |
|---|---|---|---|---|---|
| P0-01 | P0 | The canonical Render host is deployed at `https://telegram-quiz-bot-h7p1.onrender.com`. Exact release `ba2567f` passed production answer-free smoke `33246990772` and staging authenticated lifecycle smoke `33247147412`. The staging actor exercised server-timed start, idempotent replay, owned-result recovery, retake, viewer-aware rank, bookmark create/read/remove, due revision submission, dashboard and preference readback. The smoke exposed and led to fixes for the dashboard RPC transaction mode and the bookmark question-ID projection instead of masking either 503/broken queue. The isolated Render staging service then rolled back to retained release `5202bf1` with all additive migrations left in place; liveness, readiness and authenticated lifecycle smoke `33247470362` passed. It was restored to exact release `ba2567f`, where liveness, readiness and authenticated lifecycle smoke `33247559612` passed again. Blueprint, smoke workflow and rollback guide reference the canonical host. | **Partial / deployed** | `render.yaml`, `config/settings.py`, `miniapp-shell.js`, `manifest.webmanifest`, `service-worker.js`, `app.py`, `scripts/deployed_smoke.py`, `.github/workflows/deployed-smoke.yml`, `20260829031810_dashboard_rpc_transaction_mode.sql`, `20260829091919_bookmark_question_identity_projection.sql`; exact production/staging release identity, readiness, answer-free, authenticated lifecycle and application-rollback evidence. | Execute the remaining real-Telegram/manual control matrix. GitHub Pages remains a preview, not the authenticated application. |
| P0-02 | P0 | Expiry ordering is repaired and each dispatcher heartbeat evaluates all 13 due-subject states, including unclaimed dead letters and overdue/missing jobs. Production dispatch `32690912216` posted Bengali and Mathematics while preserving the already-posted Computer quiz and fail-closed the Reasoning near-duplicate. PostgreSQL cooldown/identity `P0001` rejections are narrowly translated from generic Supabase API errors into retryable content-collision outcomes, preserving chapter rotation and actionable diagnostics without reclassifying unknown database failures. Live-generation repair gives batch-wide normalized-option, distinct-relationship and answer-position instructions for the dominant validation failures. Recent exclusions carry canonical entity/relation/answer identity, every repair rechecks those tuples pairwise even when another validation rule failed first, and a read-only semantic preflight routes historical near-duplicates into the same bounded repair before spending an independent-verifier call or attempting the atomic save. If the bounded replacement is also a historical collision, it is classified as a retryable content collision so the durable retry rotates away from the exhausted chapter, including after every catalogue chapter has history. Rotation is anchored to the stable daily selection, uses only each chapter's latest history row for spacing, and locally excludes the failed anchor throughout the bounded walk; production runs `32981598729` and `32982412686` advanced Environment and History to distinct chapters instead of cycling. Environment then passed normal durable generation and posted Telegram message 2532 in run `32983417931`; History generated and checksum-verified ten immutable versions and recorded Telegram acknowledgement 2533. The 2026-08-26 durable ledger closed at 10/13 posted with no unknown deliveries; Mathematics, English and Polity remained explicit dead letters. The response schema constrains four-option item structure plus subject, canonical chapter and micro-topic identifiers to the reviewed grounding bundle. Source-backed runs receive only short allowlisted source aliases; the server maps each alias back to its exact reviewed UUID before validation and storage, so a run cannot omit or invent a source. The deterministic validator independently requires exactly ten items and exact answer bounds because duplicating the outer ten-item bound in Gemini's nested schema exceeded the provider's documented serving-state limit. When the first structurally valid batch is rejected by the independent verifier, the one existing repair budget regenerates a complete re-solved batch immediately; it never patches or publishes the rejected questions. The service-role-only recovery RPC safely requeued the audited blocked Computer job without resetting its retry history; durable attempt 5 on `31d2ded` posted Telegram message 2526, and exact release `65b3b4e` passed CI plus production and staging answer-free smoke. Production now has an observed 15-minute primary scheduler, a complete 13/13 normal day and 9.9–16.5 eligible inventory days after the latest bounded run. | **Partial / awaiting external action** | `scripts/refresh_current_affairs_sources.py`, `services/quiz_dispatcher.py`, `services/quiz_pack_service.py`, `services/chapter_selector.py`, `storage/questions_repo.py`, `storage/quiz_jobs_repo.py`, `bot.py`, `20260826080000_operator_blocked_quiz_recovery.sql`; expiry/global-state, response-schema, repair-hint, database-collision classification, audited recovery and deployed-smoke evidence. | Editorially approved reserves still remain below the 12–15-day target for Bengali, Miscellaneous and Reasoning, while chapter-level coverage is much narrower than subject-wide totals. Continue bounded replenishment; do not replay dead letters, weaken validators or force-post rejected content. |
| P0-03 | P0 | Daily attempts start on the server and ranking duration is database-derived; the required migration is applied in production and readiness is green. Client duration/response times remain untrusted telemetry. | **Implemented / deployed** | `20260820090000_server_timed_daily_attempts.sql`, `app.py`, `index.html`, attempt repository/service tests and production readiness evidence. | Legacy clients remain compatible but have null/untrusted timing and cannot receive a trusted time tie-break. Monitor anomaly reason codes after a representative attempt sample. |
| P1-01 | P1 | Generator and verifier identities are stored separately; same provider/model cannot be labeled independent; a different configured model can be selected. Generation fallback and independent-verifier selection now have separate versioned settings, so exhausted legacy verifier quota does not silently change the generator path. Production dispatch `32694725488` used `gemini-3.5-flash-lite` as the distinct verifier and safely posted the English quiz after the previous verifier model returned repeated 429s. The production migration is applied and readiness is green. | **Implemented / deployed** | `config/production.toml`, `services/gemini_provider_pool.py`, `services/question_verification.py`, verification audit repository, `20260820100000_question_verification_independence.sql`; independence/configuration tests and production contract evidence pass. | Historical records need no destructive rewrite but retain their historical basis. Monitor failure rates across normal scheduled production runs. |
| P1-02 | P1 | Publication fails when a source-less question is checked by the same model without another evidence basis. New inventory must carry a machine-checkable proof: evidence-backed subjects copy one exact contiguous atomic span from the cited verified source and prove that it contains the canonical source-language answer but no distractor proof value; conceptual mathematics and reasoning may use this exact-evidence path while calculations and puzzles still require a deterministic solver. Positionally aligned canonical proof values permit a Bengali display translation/transliteration while the independent verifier checks the displayed mapping. Generated canonical claims cannot substitute for source evidence. English and Bengali response schemas constrain the requested language artifacts, while the server derives the reviewed question form and source-proved rule identity from the cited micro-topic and exact source span and preserves both artifacts across every validation pass. Mathematics now has 28 exact solver families and reasoning has seventeen bounded solver families, including new exact coverage for age ratios, boats/streams, circle measures, two-set cardinality, bidirectional rank totals and mirror-clock time. Invalid spans, parameters, language artifacts, ambiguous answers, unsupported families and contradictory traces fail closed. Protected runs `32899639051`, `32900294697` and `32900931320` safely accepted Mathematics 4, Reasoning 5, Bengali 3 and English 4 candidates after these changes. | **Partial** | `services/content_replenishment_service.py`, `services/deterministic_verification.py`, `services/question_validation.py`, `services/question_verification.py`, response schemas and focused proof/language/projection tests. | Mandatory approved citations for every applicable daily path and solver coverage for the remaining quantitative/logic families are not complete. Keep unproved inventory out of production approval. |
| P1-03 | P1 | PIB ingestion is hardened; official RBI RSS and ISRO press-release adapters use strict host, redirect, content-type, size, date, provenance, exact-span and freshness controls. ISRO ingestion reads only first-party HTML press text—never PDFs or third-party summaries—and is supplementary, so one source outage does not discard other valid authorities. A live read-only canary accepted two current ISRO releases and safely skipped/stopped at two inapplicable or expired pages. Approved refreshes now persist each independently validated official row even when the incoming batch alone lacks full chapter breadth; the immediately following database readback remains the strict all-chapter deployment gate. Production run `32870394903` preserved three verified ISRO rows during an RBI outage, then confirmed 31 approved chapters and 120 source documents were ready. This prevents a temporary authority outage from discarding healthy rows while production coverage is still current. Current-affairs chapter/category breadth remains limited. | **Partial** | `scripts/refresh_current_affairs_sources.py`, `.github/workflows/current-affairs-sources.yml`; PIB/RBI/ISRO parser, host-confusion, expiry, provenance, exact-span, partial-refresh and event tests. | Add further reviewed official adapters and category/chapter coverage before claiming complete breadth; source-rights review remains mandatory for every new source family. Keep PDF-only or metadata-only releases out unless a separately reviewed extraction/provenance policy is approved. |
| P1-04 | P1 | Heartbeats query global due state and fail on missing, overdue, blocked, retry-exhausted, unknown or dead-lettered jobs. Individual generation failures alert operators, and the once-daily completeness gate sends one bounded answer-free summary only to the configured private Telegram admin chat; it never falls back to the public learner chat. On 30 August the normal durable path posted all 13 scheduled quizzes with ten checksum-verified questions and Telegram acknowledgement for each; no rejected content was force-posted. The post-close completeness run `33317572954` passed. | **Implemented / deployed** | `services/quiz_dispatcher.py`, `services/quiz_dispatch_runtime.py`, `bot.py`; dead-letter/overdue, private-alert and bounded-summary tests, production dispatcher evidence, 13/13 durable ledger readback and passing post-close completeness gate. | Continue daily monitoring. Static fallback artifacts are answer-free but are not a proven live origin fallback; a durable independently served fallback requires an approved storage/control-plane design. |
| P1-05 | P1 | Supabase Cron is now the production primary scheduler. It stores the GitHub workflow-dispatch credential only in Vault, dispatches the existing durable fail-closed worker every 15 minutes, records each request, reconciles the asynchronous HTTP result and exposes a service-role-only readiness contract. Production's first real cron boundary at 21:34 UTC queued the request on time, received GitHub HTTP 204 and launched successful workflow `33213118196`. GitHub's own schedule is retained only as an hourly recovery path; a native completeness event observed the same day arrived roughly six hours late, confirming it cannot be the primary SLA. Staging has the schema but no production credential or active jobs. The non-relocatable `pg_net` extension is now installed under the protected `extensions` ownership namespace in both projects; the migration refuses to recreate it while either audited scheduler requests or HTTP requests are queued, preserves the installed version, and cleared the Supabase security-advisor warning. The first post-recreation boundary exposed that pg_net resets its request sequence: the unique audit constraint rejected the dispatch before it left the database. The sequence floor was restored from durable audit history, the missed heartbeat replay returned HTTP 204, and a follow-up migration makes that continuity rule repeatable. | **Implemented / deployed** | `20260828211539_durable_primary_scheduler.sql`, `20260829094700_pg_net_extension_schema_hardening.sql`, `20260829152100_pg_net_request_sequence_continuity.sql`, `config/schedule.py`, `.github/workflows/main.yml`, `services/readiness_service.py`, migration/schedule/readiness tests; production/staging migration hash parity, production Cron run history, HTTP-response audit, advisor readback and exact deployed readiness evidence. | The current GitHub token expires on 20 September 2026; readiness fails 48 hours before its declared expiry and on any reconciled rejection. Rotate it before the renewal window. Continue measuring end-to-end on-time delivery; GitHub Actions remains a downstream execution dependency even though its unreliable scheduler is no longer primary. |
| P1-06 | P1 | Unconditional AdSense loading is removed; the Bengali hub, mock, practice, dashboard and settings pages load versioned external CSS/JS, CSP blocks inline scripts and styles, and dynamic progress uses semantic controls/SVG attributes rather than inline styles. Browser/PWA fallbacks now use the parent Citizen Affairs editorial red, link blue, canvas and text palette while Telegram theme variables retain precedence inside the Mini App. The quiz introduction keeps its campaign-tagged parent-site CTA before start. | **Partial** | `docs/BRAND_IDENTITY.md`, `miniapp-shell.js`, `index.css`/`index.js`, `mock.css`/`mock.js`, `practice.css`/`practice.js`, `dashboard.css`/`dashboard.js`, `settings.css`/`settings.js`, `legal.css`, `app.py`; brand-contract, route, CSP and mobile-browser checks pass. | Keep third-party ads off authenticated/timed pages. Reassess any future inline style requirement before weakening CSP. |
| P1-07 | P1 | Draft privacy/terms pages, authenticated export, deletion request/cancel, grace period and pseudonymous audit records are implemented. | **Partial / awaiting external action** | `privacy.html`, `terms.html`, privacy service/repository, `20260820120000_privacy_rights.sql`, `settings.html`; privacy tests pass. | Legal/controller/contact placeholders require qualified review. Do not enable deletion processing until backups, retention scope and restore/rollback are approved and tested. Consent history beyond existing preferences remains incomplete. |
| P1-08 | P1 | Vulnerable locks are updated (`cryptography 50.0.0`, `h2 4.4.1`); FastAPI, GenAI, database/client tooling and browser-test locks are refreshed; RSS uses `defusedxml` with size/type/redirect/host/time limits; security automation includes direct-requirement/lockfile parity checks. GitHub secret scanning, push protection and Dependabot security updates are enabled. | **Implemented** | requirements/locks, `scripts/check_lockfile_parity.py`, refresh script, Dependabot/security workflow and verified repository security settings; Ruff, pytest, mypy, high-severity Bandit and npm audit pass locally where noted below. | Review Dependabot/CodeQL findings as part of each release. Local `pip-audit` can be network-bound; GitHub Security is the release gate. |
| P1-09 | P1 | `mock.html` without an ID displays an answer-free searchable/filterable catalog with type, exam, subject, duration, marking and availability. Verified Telegram learners also see their latest bounded attempt status and score; an in-progress server attempt can be resumed across devices with the original idempotency key and full server-synced progress. Learners can bookmark a mock question into the existing authenticated question-practice queue without storing answer content in the browser. The public PYQ bank now presents human-reviewed questions through an explicit exam → year → shift → stage → paper → section hierarchy with exam/year/language filters, bounded pagination, official-source metadata and no answer keys. | **Implemented / content-dependent** | catalog migration/repository/service/API, cached answer-free `/api/previous-year`, authenticated `/api/tests/attempts/recent`, shared question bookmarks, `mock.html`; hierarchy, catalog, bookmark, ownership, answer-leakage and cross-device browser tests. | Breadth depends on reviewed, licensed PYQ provenance in production; never relabel generated PYQ-style material as a real paper. |
| P1-10 | P1 | Saved preferred subjects, target exams and daily question targets now drive one transparent next-study assignment on the authenticated dashboard. Due revision remains the first priority, then weak-topic practice, then goal completion, a preferred-subject quiz and finally an optional target-exam mock. Preferred due questions are ordered first in the client without hiding other scheduled reviews. The response explicitly states that broadcast quizzes are not personalized. | **Implemented / deployed** | `services/personal_learning_service.py`, `dashboard.js`, `practice.js`, `index.js`, `mock.js`; service-policy, source-contract and mobile-browser tests. | This is a deterministic versioned assignment policy, not a claim of statistically optimized learning. Monitor completion and outcome data before changing weights or introducing model-based recommendations. |
| P1-11 | P1 | Global outcome reason codes, safer release/readiness evidence, private daily-completeness alerts and a Telegram-admin-gated operations/moderation console improve operator diagnostics. The console shows database/schema state, generation/posting failures and resource/question review queues without weakening API authorization. A bounded read-only SLO report derives 1–31 day completeness, on-time delivery, missing jobs, terminal failures and per-subject aggregates from the durable job ledger without exposing quiz, learner or Telegram identifiers. Versioned engineering objectives require 99% completeness, 95% delivery within 30 minutes, zero missing or unknown-delivery jobs, and at most 1% terminal failures; the report evaluates each objective but remains diagnostic by default while a baseline is established. Post-close production workflow `33317576111` archived the policy-v1 14-day readback: 126/182 posted (69.23%), 36/182 on time (19.78%), zero missing or unknown-delivery jobs, 56 terminal failures (30.77%), and one complete day. | **Partial / deployed** | dispatcher, `services/quiz_delivery_slo.py`, `scripts/report_quiz_delivery_slo.py`, `.github/workflows/quiz-delivery-slo.yml`, `docs/QUIZ_DELIVERY_SLO_POLICY.md`, daily private alert, readiness/version endpoints, `routes/admin.py`, `admin.html`, `admin.css`, `admin.js`; SLO policy/privacy, admin authorization, alert privacy and frontend route tests. | External tracing/error aggregation and independent alert-delivery monitoring remain observability work. The rolling baseline still misses completeness, on-time and terminal-failure objectives because it includes thirteen pre-remediation days; promote `--fail-on-slo` only after a representative sustained window meets policy and the alert path is independently monitored. |
| P1-12 | P1 | Immutable answer-free quiz/test payloads now have ETags and public CDN caching; personalized responses remain `no-store`; write rate limits remain. | **Partial** | `app.py`; API caching/privacy tests pass. | Edge/IP read quotas, aggregate short caching, bot protection and query-budget monitoring require the production edge owner. |
| P1-13 | P1 | Pinned security/deployed-smoke workflows, Dependabot and immutable release metadata are present. Repository and job permissions default to read-only. `main` requires the quality, mobile-browser, dependency/static-audit and both CodeQL checks, linear history and resolved conversations; force-push and deletion are disabled. Generated answer-free fallback snapshots are retained as bounded workflow artifacts instead of being pushed onto the protected branch. | **Partial / deployed** | `.github/workflows/main.yml`, `.github/workflows/security.yml`, `.github/workflows/deployed-smoke.yml`, `.github/dependabot.yml`, `/version`; verified GitHub Actions default permissions and branch-protection settings. | The solo owner retains administrator bypass so maintenance is not deadlocked. Add a second qualified reviewer before enabling mandatory production-environment approvals. |
| P2-01 | P2 | No reviewed corpus expansion was fabricated. Durable claims round-robin subject slots and prefer the least recently claimed subject; bounded exponential retry and actionable rejection codes prevent unsupported topics from monopolising model calls. Evidence-backed candidates prove against one verbatim atomic span, calculations and puzzles retain exact solver gates, and historical identities plus same-batch duplicates are removed before persistence and job accounting. The bounded repair always regenerates and re-verifies a complete batch. Protected run `32874118865` added Computer 5, Current Affairs 5, Economics 5 and Polity 3; a transient read-only inventory-report timeout was subsequently covered by a bounded transport-only retry. Runs `32899639051`, `32900294697` and `32900931320` added reviewed proof/language candidates without weakening any gate. On 2026-08-26, bounded production runs `33015784650`, `33015997979`, `33016214000`, `33017339215`, `33017977251` and `33018903794` completed successfully; the four 25-job runs accepted 348 candidates while rejecting 381 unsafe, unsupported or duplicate candidates. Runs `33212488703` and `33213600104` each accepted another 77 candidates without weakening the gates. Run `33233058687` claimed 25 targets, completed 22 safely, failed three closed, accepted 77 candidates and rejected 128. Post-delivery-window run `33317697604` claimed 25 targets, completed 22 batches safely, failed three closed on `content_rejected`, accepted 66 candidates and rejected 164; its report raised subject reserves to 9.9–16.5 days with zero repeated exposure and zero same-quiz duplicates in the measured 30-day window. Yield is now constrained by verified source breadth, chapter-level difficulty mix and novelty, so automation cannot safely replace editorial review. | **Partial / awaiting external action** | Protected replenishment runs `32628857437`, `32651114106`, `32678802988`, `32693923555`, `32694850654`, `32870392758`, `32874118865`, `32899639051`, `32900294697`, `32900931320`, `33015784650`, `33015997979`, `33016214000`, `33017339215`, `33017977251`, `33018903794`, `33212488703`, `33213600104`, `33216545212`, `33233058687` and `33317697604`; `20260824052500_fair_content_replenishment_claims.sql`, replenishment/verification services, production event evidence, inventory reporting and focused schema/projection/solver/repair/backoff/fairness/fail-closed tests. | A qualified Bengali/English/math/reasoning content team must review evidence, translations and proofs and approve blueprint-level reserves. Remaining mathematics topics need reviewed source alignment and supported deterministic proof families. Rejected candidates must not be force-published or accepted by weakening validators. |
| P2-02 | P2 | Collision and semantic-near checks remain. The protected production report now measures answer-free 30-day repeated exposure and same-quiz duplicate events per subject against the audit targets; all 13 subjects reported 0% repeated exposure and zero same-quiz duplicates on 2026-08-23. | **Implemented / deployed** | `services/question_inventory.py`, `scripts/report_question_inventory.py`, production replenishment run `32628857437` and focused exposure-metric tests. | Continue monitoring each protected run, quarantine confirmed duplicates through moderation and keep the target below 0.5% with zero same-test duplicates. Do not automate destructive backfills without content review. |
| P2-03 | P2 | A bounded read-only diagnostic now deduplicates first completed responses by learner/question and reports facility with Wilson confidence, rest-score point-biserial discrimination, nonfunctioning distractors and authored-difficulty mismatches. Explicit sample gates abstain below 100 responses, 50 learners, or 10 learners in either discrimination group. Output excludes learner/attempt IDs, selected/correct option indexes and content; it cannot retire questions or alter difficulty/mastery. The 90-day production canary saw 1,633 usable responses across 1,052 questions, so all correctly remained `collect_more_data`. Pinned weekly/manual production run `32690481721` generated and archived the aggregate diagnostic for 30 days. | **Partial / deployed tooling** | `services/question_calibration.py`, `storage/question_calibration_repo.py`, `scripts/report_question_calibration.py`, `.github/workflows/question-calibration.yml`, `docs/QUESTION_CALIBRATION_POLICY.md`; focused policy, privacy, repository-bound and production workflow canary evidence. | A learning-science owner must validate thresholds and sampling bias, define human retirement/reinstatement and mastery-correction governance, and wait for adequate per-question samples. Do not automate content or learner-state mutations from these diagnostics. |
| P2-04 | P2 | Learner reporting exists after daily and practice answers with reason/details, authenticated APIs and moderation thresholds. The service-role-only reporter-status projection is deployed; it returns only a learner's own report/case status and closed-case resolution, never question text, options or answers. All 59 tracked migrations that have reached production align by version/name and pinned source identity. Thirty-seven historical sources were independently matched byte-for-byte; later schema-equivalent sources were fingerprint-matched before their ledger records were reconciled. The dashboard-transaction, bookmark-projection, extension-hardening, sequence-continuity, guarded validation-dead-letter recovery and stable-subject replenishment sources were independently read back from both hosted ledgers and matched repository MD5 before guarded version reconciliation. A one-time staging report canary exposed that the older learner-status ledger row was absent there; its repository source matched hosted MD5 `e4de3dc550bf911651011134e6d9a463`, the tracked version was restored, authenticated status readback passed, and the exact synthetic report/event/case were removed. | **Implemented / deployed** | `database/migration_ledger.py`, `scripts/check_migration_ledger_sources.py`, `20260823065257_learner_report_status_projection.sql`, `20260829163136_guarded_validation_dead_letter_recovery.sql`, `20260830095000_source_optional_stable_replenishment.sql`, `20260830095800_return_new_replenishment_jobs.sql`, migration workflows, `app.py`, moderation/report repositories and focused contract/API tests; disposable-database and production-plan runs, plus exact hosted source/ledger and staging lifecycle readback. | Keep the source-hash gate and read-only plan green before every future migration. Never repair migration history without independent source/schema equivalence evidence. |
| P2-05 | P2 | Reminder/retention scheduling and the learner control remain disabled, the browser persists `false`, and the authenticated API rejects a crafted opt-in. The deployed additive contract provides versioned consent, validated timezone/quiet hours, immediate pending-job cancellation, per-user/date idempotency, expiring leases, a five-attempt ceiling, permanent-chat suppression, bounded backoff/claim size, answer-free jobs, privacy-safe aggregate metrics and a synthetic-only canary scope. A bounded worker now implements the lease/completion protocol but defaults to a no-op, has no live mode, requires an exact synthetic learner plus explicit confirmation, cancels anything outside that scope, and emits only a fixed answer-free message. Production verification confirms the exact contract still reports `deliveryEnabled: false`. A staging-ledger comparison found that this additive contract had never been applied there; the exact tracked source was applied empty, read back at MD5 `ea17591b8070d6ef1708acac43ef74cf`, and reconciled to version `20260824033823` without enabling delivery or creating consent/job rows. | **Partial / deployed and safely disabled** | `20260824033823_durable_reminder_consent_delivery.sql`, `services/reminder_delivery_service.py`, `storage/reminder_delivery_repo.py`, `scripts/run_reminder_delivery_worker.py`, `docs/REMINDER_DELIVERY_POLICY.md`, `settings.html`, `settings.js`; worker safety/classification tests, CI `32687642009`, read-only plan `32687770225`, deployment and contract verification `32687812958`, plus exact staging source/privilege/empty-table readback. | Fund/select a reliable scheduler and pass an approved synthetic private-message canary before enabling any real-user consent or send. |
| P2-06 | P2 | The product remains honestly Bengali-only. Settings exposes only Bengali and the authenticated preference API now rejects crafted Hindi/English UI preferences instead of persisting an unsupported promise. Assessment-content language remains a separate concern. A complete translation catalogue has not been introduced. | **Partial** | `services/personal_learning_service.py`, `settings.html`, `docs/LOCALIZATION_READINESS.md`; preference validation and UI contract tests. | Do not advertise Hindi/English until every visible/dynamic/offline/legal/accessibility string, search normalization and mobile/manual QA is complete. |
| P2-07 | P2 | Anonymous web users can discover the public catalogue and inspect an answer-free, read-only question preview. The home and each quiz intro now provide an explicit handoff to the named Telegram Mini App, including a quiz-specific `startapp` deep link. Scores, attempts, ranks and progress still require verified Telegram launch data; the HMAC boundary is unchanged. | **Partial / safely constrained** | Public catalogue and quiz projections, preview-only browser mode, Telegram handoff browser tests. | Guest persistence and account linking still require identity, abuse, privacy and attempt-integrity review. Do not weaken Telegram HMAC validation or merge browser-local progress into an account without that design. |
| P2-08 | P2 | Catalog discovery, the authenticated dashboard and a learner-facing syllabus map form a deterministic next-study loop. The map now overlays private progress for each mapped knowledge point, micro-topic, chapter and subject; its explicit criteria require score 80 plus two attempts, exclude uncovered content from the denominator, show due revision, and never label a micro-topic with no mapped content complete. The production canary mapped 1,362 active knowledge points to 288 of 648 reviewed micro-topics (44.4%), so the remaining content is honestly shown as not prepared. This is not advertised as a diagnostic. | **Partial / deployed tooling pending release** | `services/personal_learning_service.py`, `services/syllabus_catalog_service.py`, `services/syllabus_progress_service.py`, `/api/syllabus`, authenticated `/api/me/syllabus-progress`, `docs/SYLLABUS_PROGRESS_POLICY.md`, syllabus/dashboard/practice/home/mock flows and focused policy/API/mobile-browser tests. | Verified content still covers fewer than half of reviewed micro-topics. Product and learning-science owners must validate diagnostic design and longitudinal adjustment metrics before claiming a complete adaptive journey; content expansion remains subject to provenance and editorial gates. |
| P2-09 | P2 | Existing accessibility primitives are preserved, a manual WCAG 2.2 AA matrix is documented, and pinned axe-core Playwright checks cover the Bengali preparation hub, quiz start/result, authenticated dashboard, settings, syllabus map, revision-practice/feedback, mock catalog/PYQ hierarchy and mock-result views at all four Android target widths. The expanded checks corrected chart semantics, insufficient contrast, undersized catalog controls and undersized inline source links. | **Partial** | `docs/ACCESSIBILITY_TEST_MATRIX.md`, `tests/browser/accessibility.spec.js`, `tests/browser/quiz-flow.spec.js`, `tests/browser/practice.spec.js`, `tests/browser/mock-flow.spec.js`, learner-facing HTML/CSS; 40 automated axe checks pass. | Execute the manual matrix with assistive technologies before production sign-off; automation cannot verify real Telegram and assistive-technology behavior. |
| P2-10 | P2 | Request contracts are isolated in `api_models.py`; public quiz delivery, timed-test attempts, learner workflows, admin moderation, privacy-projected leaderboards, public catalogue, static/PWA delivery and system endpoints are isolated in focused route modules. Scheduled-job health, dispatch and recovery orchestration is isolated from the subject generation/posting entry point. Primary pages use external CSS/JS and no longer need inline runtime styles. | **Implemented** | Service/repository modules, `api_models.py`, `routes/quizzes.py`, `routes/test_attempts.py`, `routes/learner.py`, `routes/admin.py`, `routes/leaderboards.py`, `routes/catalog.py`, `routes/static_pages.py`, `routes/system.py`, `services/quiz_dispatch_runtime.py`, external frontend assets; full pytest, Ruff and mypy pass. | Keep future HTTP and scheduling behavior in focused modules; retain `app.py` and `bot.py` as composition/entry points rather than adding new domain logic there. |
| P2-11 | P2 | Accidental FUSE artifact is removed/ignored and current release, architecture and rollback documentation is added. | **Implemented** | `.gitignore`, removed `.fuse_hidden*`, remediation/release/architecture docs. | Archive contradictory legacy runbooks after owner review rather than deleting potentially useful history automatically. |
| P2-12 | P2 | Security, contribution, conduct, roadmap, issue/PR templates and content provenance policy are added. | **Partial / awaiting external action** | root governance files, `.github` templates, `docs/PUBLIC_ROADMAP.md`, `docs/CONTENT_PROVENANCE_AND_LICENSING.md`. | Repository owner must choose an OSI license and confirm code/content ownership. No license was guessed. |

## 1 September production and proof-coverage checkpoint

- Exact release `83fa23102deeb37a5d167a1bb5d0df4263aad019` reached Render, returned every
  readiness check green, served the Telegram practice-action recovery assets and
  passed canonical deployed smoke run `33471218082`.
- Bounded fail-closed replenishment runs `33471317473`, `33490471626` and
  `33490784093` accepted 34 independently gated candidates in total while unsafe,
  duplicate and unsupported candidates remained rejected. English crossed the
  15-day subject reserve; Bengali reached 13.4 days and Miscellaneous 12.5 days.
  Reasoning remained at 12.4 days after one fully rejected batch and one provider
  generation failure; no candidate was force-published.
- The next solver-coverage change adds three mathematics and three reasoning
  families for common syllabus gaps. Its focused suite covers successful exact
  solutions and invalid-parameter fail-closed behavior; production replenishment
  must continue only after the normal release gates deploy that code.

## 28 August production checkpoint

- Release `d262a46` is live on both Render services. Main Tests run
  `33163559923`, Security run `33163560070`, staging preflight
  `33164013282`, and canonical answer-free deployment smoke `33164016801`
  passed against the exact release.
- Migration `20260827040000_deduplicate_open_content_replenishment_jobs.sql`
  converted 1,954 redundant open replenishment rows into retained,
  `superseded_open_job` audit history and left 103 canonical open targets. A
  partial unique index and concurrency-safe ensure functions now prevent more
  than one open job per subject/micro-topic target. Both hosted contracts report
  ready with zero duplicate open jobs.
- Bounded production replenishment run `33162886841` claimed five distinct
  targets, accepted 16 independently gated candidates, rejected 24 unsafe or
  duplicate candidates, and completed with 103 open jobs for 103 distinct
  targets and no active lease.
- Larger bounded production replenishment run `33164314150` completed
  successfully across 25 distinct targets, accepted 66 independently gated
  candidates and safely rejected 81. The durable backlog remained bounded at
  103 open jobs for 103 distinct targets, with zero active leases after the
  run.
- Production and staging stored the two newest migration sources as one exact
  statement each. Their byte identities matched the repository
  (`af474c52612e3876d9fc6fb63ce01354` and
  `b8ca0e0c5320733f6ec6ad3a4260de8a`) before guarded ledger-only version
  reconciliation. The
  production ledger now has exactly 51 version/name/source-pinned migrations
  with no local/remote mismatch. Read-only production plan `33163582403`
  independently reported the remote database up to date.
- Normal recovery dispatches beginning with `33162078817` increased the
  27 August ledger from 8/13 to 11/13 posted and the in-progress 28 August
  ledger to 9/13 posted. Run `33187325324` used release `6c955c1`, generated,
  independently verified and posted Current Affairs as Telegram message 2555.
  Reasoning and Mathematics validation failures plus History and Environment
  historical collisions stayed in durable retry; none was force-posted.

## Verification evidence

### 30 August validation-recovery checkpoint

- Migration `20260829163136_guarded_validation_dead_letter_recovery.sql` adds a
  service-role-only, exact-state recovery operation for empty, unacknowledged
  `validation_failed` dead letters. It preserves retry history, requires a
  distinct active replacement chapter and records actor, reason, release and
  chapter movement. The stored statement in staging and production matches the
  repository MD5 `9eac16f908e3b760049efae42244f8c9`; both hosted ledgers contain all
  57 tracked versions. Anonymous and authenticated execution is denied, while
  service-role execution is available. Read-only production plan `33263703289`
  reported the remote database up to date, and post-DDL advisor readbacks had no
  warning or error.
- Release `774d35d` passed Tests `33263454128` and Security `33263454119`.
  Release `5de72c1` then changed verified-inventory assembly to quarantine an
  invalid candidate without discarding safe peers, enforce the exact daily
  difficulty distribution and request the corresponding replenishment mix.
  It passed Tests `33264153842`, Security `33264153834`, production smoke
  `33264280058` and authenticated staging smoke `33264308366`; both Render
  services are live at that exact release.
- The guarded 29 August Mathematics recovery retained retry count 8 and moved
  the empty dead letter to a distinct chapter. Normal dispatches exercised the
  new retry rotation through two further chapters; rejected duplicate and
  semantic-contract batches remained unpublished. The day closed at 12/13
  posted, with Mathematics explicit at retry 10, zero saved questions and no
  Telegram acknowledgement. No validator was weakened and no force-post was
  used.
- On 30 August, Mathematics first failed closed on materially duplicate options,
  automatically rotated from `ত্রিকোণমিতি` to
  `Data Interpretation, পরিসংখ্যান ও সম্ভাবনা`, and the next normal durable
  attempt `33292913733` generated, checksum-verified and posted ten questions as
  Telegram message 2577. English, Miscellaneous, Polity and Geography then
  posted normally. Science retained its first rejected collision as a durable
  retry and normal recovery run `33304645012` posted ten checksum-verified
  questions as message 2582. Economics, History, Environment and Current
  Affairs subsequently completed through the same normal durable path. The day
  closed 13/13 with ten integrity-verified questions per subject, acknowledged
  Telegram message IDs 2574–2586, zero unknown delivery and no force-post.
  Post-close daily-completeness workflow `33317572954` passed. Diagnostic SLO
  workflow `33317576111` archived the answer-free 14-day report: the latest day
  is complete, the window has zero missing or unknown-delivery jobs, and the
  older pre-remediation days keep the rolling policy baseline below target.
- Bounded production replenishment `33292750041` claimed 25 distinct targets,
  accepted 76 independently gated candidates, rejected 132 unsafe or duplicate
  candidates, completed seven targets and retained eighteen for bounded retry.
  Follow-up bounded runs `33293161441` and `33293489270` accepted another 98
  and 74 candidates while rejecting 103 and 137 respectively; unsupported or
  duplicate material remained out of inventory. Eligible reserves now range
  from 9.6 to 16.1 days by subject, Mathematics reached 12.5 days, and the
  measured 30-day window still has zero repeated exposure and zero same-quiz
  duplicates. Mathematics Geometry has 23 easy, 25 medium and four hard eligible
  candidates, which is enough to satisfy the exact 3/5/2 daily distribution.
  The protected capacity report now exposes answer-free per-chapter counts and
  shortages against that exact mix across every runtime chapter, so a large
  subject-wide reserve can no longer hide a hard-question or chapter gap.
- A live staging readiness probe exposed one transient contract-read failure:
  eleven otherwise healthy checks were collapsed into one false group and the
  endpoint briefly returned 503. Direct readback showed every staging contract
  ready and the next uncached request returned 200. Contract reads now retry
  once independently and persistent failures remain isolated and fail-closed;
  one unavailable contract can no longer erase evidence from ten healthy ones.
  Release `730232e` passed Tests `33293428980` and Security `33293428923`, is
  live on production deploy `dep-da9rf65g1s2s73b9vrc0` and staging deploy
  `dep-da9rf6942hec738nnuv0`, and passed production smoke `33293609917` plus
  authenticated staging lifecycle smoke `33293611267`. Three consecutive
  uncached readiness probes on each service returned HTTP 200 with no failed
  checks.
- Inventory artifact run `33304812157` retained the answer-free subject,
  chapter and difficulty capacity report for 30 days. It exposed that the
  stable-subject runtime syllabus was broader than the older database queue
  predicate: 85 verified-source micro-topic targets were ineligible solely
  because their chapter was not in the current-affairs-style rotation gate.
  Migrations `20260830095000_source_optional_stable_replenishment.sql` and
  `20260830095800_return_new_replenishment_jobs.sql` now admit those verified
  stable topics while preserving the strict current-affairs allowlist, and
  correctly return jobs inserted by the first call despite PostgreSQL's
  data-modifying-CTE snapshot rule. Both hosted ledgers contain all 59 tracked
  versions and match repository MD5s `ab3f913d9af0afa1db75a6599e3e0ae2`
  and `ba1b9f9bdd908631d317103767c18f16`; the first production ensure call
  returned 15 newly eligible distinct targets. Read-only production plan
  `33306053981` reported the 59-version database up to date. Post-DDL Supabase
  advisors have no warning or error in either environment.
- Provider-heavy replenishment no longer runs during the 07:00–19:00 IST quiz
  window; protected PR 74 moved its two automatic runs to 22:50 and 04:50 IST
  while preserving bounded manual execution. Release `6c4505b` passed Tests
  `33305742098` and Security `33305742107`, is live on production deploy
  `dep-daa036lg1s2s73bn8n00` and staging deploy
  `dep-daa036qjnfac73f43bn0`, and passed production smoke `33305930681` plus
  authenticated staging lifecycle smoke `33305932363`.
- After the delivery window closed, bounded production replenishment
  `33317697604` processed 25 distinct targets, completed 22 batches, failed
  three closed on content rejection, accepted 66 independently gated
  candidates and rejected 164. Its archived answer-free capacity report shows
  9.9–16.5 eligible days by subject, with zero repeated exposure and zero
  same-quiz duplicates in the measured 30-day window.

### 29 August production scheduler checkpoint

- Migration `20260828211539_durable_primary_scheduler.sql` passed the complete
  disposable PostgreSQL 17 migration chain, was applied to staging and
  production, and its single stored statement matched the repository MD5
  `022a4a02595b0c5e0e3eacddd2d04ea7` in both hosted ledgers before their
  generated versions were reconciled to the tracked version.
- Production Supabase Cron owns the 15-minute heartbeat. The 21:34 UTC job ran
  on its exact boundary, GitHub accepted the request with HTTP 204, and
  workflow `33213118196` completed successfully. The production contract and
  deployed `/health/ready` report the scheduler ready. Staging's duplicate
  activation credentials and three jobs were removed after the canary.
- Exact release `d80e2f8` passed Tests `33212588574`, Security `33212588516`,
  both answer-free canonical deployment smokes (`33212797305` and
  `33212797481`), and HTTP 200 readiness on both Render services. Subsequent
  scheduler-scope changes retain the same database contract and tests.
- The final normal 28 August retry (`33211403760`) left Mathematics and
  Reasoning as explicit validation dead letters at retry 8. The day closed at
  11/13 posted with no unknown delivery and no rejected content force-posted.
- Bounded replenishment run `33212488703` claimed 25 distinct targets, accepted
  77 independently gated candidates and safely rejected 136 unsupported,
  duplicate or provider-failed candidates. Eligible reserves increased to
  6.7–10.6 days by subject; the durable queue ended with 102 unique open targets
  and no active lease. Provider demand produced several 503 responses, but the
  bounded failover/retry path completed without weakening validation.
- Exact release `5202bf1` passed Tests `33232433337` and Security
  `33232433338`. Both Render services are live at that commit. Production
  answer-free smoke `33232581875` and staging authenticated lifecycle smoke
  `33232580040` passed. The latter covers attempt retry, owned result recovery,
  retake, rank, bookmark cleanup, revision, dashboard and preferences.
- Migrations `20260829031810_dashboard_rpc_transaction_mode.sql` and
  `20260829091919_bookmark_question_identity_projection.sql` corrected the two
  real lifecycle failures found by that staging actor. Both hosted statement
  hashes match the tracked sources; production dry-run `33232523903` reports
  the database up to date. Post-DDL advisors contain informational deny-by-
  default/unused-index observations only, with no warning or error.
- The one-time report lifecycle canary returned HTTP 200 for authenticated
  submission and learner-owned status readback. It also found that staging had
  lost the older `20260823065257_learner_report_status_projection.sql` ledger
  row. The restored hosted statement matches repository MD5
  `e4de3dc550bf911651011134e6d9a463`; the function remains executable only by
  `service_role`, staging readiness is HTTP 200, and the canary's single report,
  append-only audit event and isolated moderation case were removed using
  exact-identity and exclusivity guards.
- A complete tracked-version comparison then exposed one further staging-only
  omission: the disabled reminder contract. Its exact repository source was
  applied and matched hosted MD5 `ea17591b8070d6ef1708acac43ef74cf`
  before guarded version reconciliation. Both reminder tables remain empty,
  `anon`/`authenticated` cannot execute the contract, and delivery remains
  unavailable; no production or learner state was changed.
- Migration `20260829094700_pg_net_extension_schema_hardening.sql` moved
  `pg_net` extension ownership from `public` to `extensions` while preserving
  each project's installed version. Both hosted statements match repository
  MD5 `4c3411cfee52734a924723cbc0f61aea`; the queue guards were empty, the worker
  and `net.http_post` remained available, both deployed readiness endpoints
  returned HTTP 200, and both security-advisor readbacks contain no warning or
  error. Release `52dab7e` passed Tests `33233527778`, Security `33233527787`
  and read-only production migration plan `33233615706` before production DDL.
- The 09:49 UTC production Cron invocation then failed closed on a duplicate
  request ID because recreating pg_net also recreated its sequence. No GitHub
  dispatch or Telegram delivery occurred. The sequence was advanced to durable
  audit ID 50, replay ID 51 reconciled with HTTP 204, and migration
  `20260829152100_pg_net_request_sequence_continuity.sql` now derives the floor
  from retained audit history without ever lowering an already newer sequence.
  Its hosted statements match repository MD5
  `fdf579cd3c01a8753f365e1d18b7c23a`; release `ba2567f` passed Tests
  `33246547580`, Security `33246547464`, pre-DDL plan `33246635379`, and the
  post-DDL up-to-date plan `33246682514`.
- The first normal boundary after sequence repair ran at 10:04 UTC, allocated
  the new request ID 52 and reconciled to GitHub HTTP 204. Exact release
  `ba2567f` is live on both Render services; production answer-free smoke
  `33246990772` and staging authenticated lifecycle smoke `33247147412` passed.
  Staging required one clean-cache redeploy after Render marked a stale cached
  runtime live; the version gate rejected that stale instance before any
  authenticated test ran.
- The staging application rollback gate is now exercised rather than inferred.
  Render rollback deploy `dep-da9b2tpf2nfc73euqc30` activated retained release
  `5202bf1` without reversing additive migrations; both health endpoints and
  authenticated lifecycle smoke `33247470362` passed. Standard deploy
  `dep-da9b3n1srm7s73bpqhog` then restored exact release `ba2567f`; both health
  endpoints and authenticated lifecycle smoke `33247559612` passed again.
- Bounded production replenishment `33233058687` accepted 77 candidates and
  rejected 128 without weakening validation. Eligible reserves are now
  Bengali 7.9, Computer 10.8, Current Affairs 12.7, Economics 10.6, English
  8.3, Environment 10.4, Geography 10.5, History 10.2, Mathematics 9.4,
  Miscellaneous 7.5, Polity 11.0, Reasoning 8.5 and Science 9.3 days.

- `ruff check .`: pass.
- `mypy`: success, 90 configured production source files.
- Local `pytest -q`: **657 passed, 39 skipped**, one upstream Starlette/httpx deprecation warning; CI run `33293428980` passed the disposable PostgreSQL 17 migration chain, full suite and mobile-browser gate for release `730232e`.
- Playwright: **140 passed** across the four supported Android viewports.
- `pip-audit -r requirements.lock`: no known vulnerabilities.
- `bandit -r . -lll`: no high-severity findings.
- `npm audit`: zero vulnerabilities at lock refresh.
- `git diff --check`: pass.
- Disposable PostgreSQL integration tests and rollback rehearsal remain CI/release gates; they must not be inferred from unit or browser tests.
