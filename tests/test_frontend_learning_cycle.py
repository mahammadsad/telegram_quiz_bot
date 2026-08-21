import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
PRACTICE = (ROOT / "practice.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "dashboard.html").read_text(encoding="utf-8")
SETTINGS = (ROOT / "settings.html").read_text(encoding="utf-8")
MOCK = (ROOT / "mock.html").read_text(encoding="utf-8")
SHELL = (ROOT / "miniapp-shell.js").read_text(encoding="utf-8")
WORKER = (ROOT / "service-worker.js").read_text(encoding="utf-8")


def test_quiz_ui_autosaves_resumes_navigates_and_confirms_submission():
    for contract in (
        "telegram-quiz-draft:",
        "localStorage.setItem",
        'id="btn-resume"',
        'id="question-navigator"',
        'id="btn-mark"',
        'id="submit-modal"',
        "markedForReview",
        "responseTimes",
        "durationSeconds",
    ):
        assert contract in INDEX
    assert "initData:tg.initData" not in INDEX.split("function saveDraft", 1)[1].split(
        "function discardDraft", 1
    )[0]


def test_quiz_result_links_the_complete_learning_cycle():
    assert 'id="btn-wrong-practice"' in INDEX
    assert 'id="btn-revise"' in INDEX
    assert 'id="btn-retake"' in INDEX
    assert 'id="btn-dashboard"' in INDEX
    assert 'id="btn-personal-dashboard"' in INDEX
    assert "bookmark-submit" in INDEX
    assert "result-average" in INDEX
    assert "result-unanswered" in INDEX
    assert 'byId("btn-revise").addEventListener("click",openRevisionPractice)' in INDEX.replace(
        " ", ""
    )
    assert 'navigateTelegram("practice.html?source=due")' in INDEX.replace(" ", "")
    assert 'byId("btn-revise").addEventListener("click",loadResources)' not in INDEX.replace(
        " ", ""
    )


def test_quiz_result_survives_refresh_and_retake_gets_a_new_identity():
    assert 'get("attempt")' in INDEX
    assert '"/attempt/"+encodeURIComponent(value)' in INDEX.replace(" ", "")
    assert 'headers:{"X-Telegram-Init-Data":isTelegram?tg.initData:""}' in INDEX.replace(" ", "")
    assert 'url.searchParams.set("attempt",requestedAttemptId)' in INDEX.replace(" ", "")
    assert 'url.searchParams.delete("attempt")' in INDEX.replace(" ", "")
    assert "clearResultLocation();" in INDEX.split("function startQuiz", 1)[1].split("function prepareQuizHeader", 1)[0]


def test_practice_ui_keeps_answers_hidden_until_authenticated_post():
    assert '"/api/me/wrong-questions?limit=100"' in PRACTICE
    assert '"/api/me/reviews/due?limit=100"' in PRACTICE
    assert '"/api/me/practice/"' in PRACTICE
    post = PRACTICE.split('fetch(api("/api/me/practice/"', 1)[1]
    assert "selectedIndex:selected" in post
    assert "result.correctIndex" in post
    assert "rows[index].correctIndex" not in PRACTICE


def test_personal_dashboard_uses_private_sql_analytics_without_settings_controls():
    assert '"/api/me/dashboard"' in DASHBOARD
    assert '"/api/me/preferences"' not in DASHBOARD
    assert '"/api/leaderboards/"' in DASHBOARD
    assert "subjectPerformance" in DASHBOARD
    assert "progressOverTime" in DASHBOARD
    assert 'id="settings-card"' not in DASHBOARD
    assert 'id="daily-target"' not in DASHBOARD
    assert 'id="quiz-mode"' not in DASHBOARD
    assert "--tg-theme-bg-color" in DASHBOARD
    assert "prefers-reduced-motion" in DASHBOARD
    assert '"miscellaneous":"বিবিধ সাধারণ জ্ঞান"' in DASHBOARD
    assert '"static-gk"' not in DASHBOARD


def test_preferences_and_privacy_have_a_dedicated_settings_page():
    for contract in (
        "<title>পছন্দ ও গোপনীয়তা</title>",
        'href="settings.html" aria-current="page"',
        '"/api/me/preferences"',
        'id="daily-target"',
        'id="quiz-mode"',
        'id="leaderboard-visible"',
        'id="username-visible"',
        'id="revision-sound"',
        'id="revision-vibration"',
        'id="test-sound"',
        'localPreference("revisionSoundEnabled"',
        "--tg-theme-bg-color",
        "prefers-reduced-motion",
    ):
        assert contract in SETTINGS
    assert 'class="active"' in SETTINGS
    assert "পছন্দ ও গোপনীয়তা" in SETTINGS
    assert "settings.html" in INDEX
    assert "settings.html" in DASHBOARD
    assert "settings.html" in PRACTICE
    assert "দৈনিক স্মরণবার্তা — শীঘ্রই আসছে" in SETTINGS
    reminder = re.search(r'<input id="reminder"[^>]+>', SETTINGS)
    assert reminder and "disabled" in reminder.group(0)
    assert "dailyReminderEnabled:false" in SETTINGS


def test_only_a_complete_locale_is_advertised() -> None:
    language = re.search(r'<select class="field" id="language"[^>]*>(.*?)</select>', SETTINGS)
    assert language
    assert language.group(1).count("<option") == 1
    assert 'value="bn"' in language.group(1)
    assert 'value="hi"' not in language.group(1)
    assert 'value="en"' not in language.group(1)
    assert 'supportedLocales = Object.freeze(["bn"])' in SHELL


def test_pwa_cache_is_fail_closed_for_answer_material() -> None:
    for source in (INDEX, DASHBOARD, PRACTICE, SETTINGS, MOCK):
        assert 'rel="manifest" href="manifest.webmanifest"' in source
        assert 'src="miniapp-shell.js" defer' in source
    assert 'X-Answer-Free-Payload' in WORKER
    assert 'response.headers.get("X-Answer-Free-Payload") === "1"' in WORKER
    assert 'path.startsWith("/api/")' in WORKER
    for sensitive in ("attempt", "submit", "leaderboard", "correctIndex", "explanation"):
        assert sensitive not in WORKER.split("const SHELL_URLS", 1)[1].split("];", 1)[0]
    assert 'fetch(request, {cache: "no-store"})' in WORKER


def test_missing_quiz_message_is_user_facing_not_an_operator_instruction() -> None:
    assert "এই কুইজটি এখনও পাওয়া যাচ্ছে না" in INDEX
    assert "API status:" not in INDEX
    assert "Bot workflow আবার চালালে" not in INDEX


def test_timed_mock_ui_has_durable_progress_sections_and_results() -> None:
    for contract in (
        "telegram-mock-draft:",
        '"/attempts/start"',
        '"/progress"',
        '"/sections/advance"',
        '"/submit"',
        'id="section-strip"',
        'id="timer"',
        'id="palette"',
        'id="mark-review"',
        'id="submit-modal"',
        'id="section-analysis"',
        'id="topic-analysis"',
        "autoSubmitPending",
        "markedForReview",
        "responseTimeSeconds",
    ):
        assert contract in MOCK
    draft = MOCK.split("function saveDraft", 1)[1].split("function discardDraft", 1)[0]
    assert "initData" not in draft
    assert "correctIndex" not in draft
    assert "explanation" not in draft


def test_revision_feedback_is_explicitly_server_mode_only_and_idempotent():
    assert 'queueMode=data.mode' in PRACTICE
    assert 'sourceType:queueSource,mode:queueMode' in PRACTICE
    assert 'result.mode!=="revision"||result.isCorrect||feedbackPlayed[attemptId]' in PRACTICE
    assert 'feedbackPlayed[attemptId]=true' in PRACTICE
    assert 'queueMode!=="revision"||!preferences.sound' in PRACTICE
    assert 'attemptId:attemptId' in PRACTICE
    assert 'savePending(true)' in PRACTICE
    assert 'submitting||selected===null' in PRACTICE
    assert "AudioContext" not in INDEX
    assert "revisionMistakeFeedback" not in INDEX


def test_current_user_and_revision_preferences_are_visible_and_persisted():
    for contract in (
        'id="identity-card"',
        'id="your-rank"',
        'className="you"',
        'badge.textContent="আপনি"',
        "data.currentUser",
        "data.separatorRequired",
        '<option value="overall_rank">সামগ্রিক র‍্যাঙ্ক</option>',
    ):
        assert contract in DASHBOARD
    for contract in (
        'id="revision-sound"',
        'id="revision-vibration"',
        'id="test-sound"',
        'localPreference("revisionSoundEnabled"',
    ):
        assert contract in SETTINGS
    assert 'id="weak-practice"' in DASHBOARD
    assert 'source=weak_topic&subject=' in DASHBOARD
    assert 'el("page-title").textContent="কুইজ ড্যাশবোর্ড"' in DASHBOARD
    assert 'el("page-link").textContent="আমার ড্যাশবোর্ড"' in DASHBOARD
    assert 'id="bookmark-practice"' in DASHBOARD
    assert 'id="bookmarks-card"' not in DASHBOARD
    assert 'fetch(api("/api/me/bookmarks")' not in DASHBOARD
    assert 'id="r-overdue"' in DASHBOARD
    assert 'id="revision-subjects"' in DASHBOARD
    assert 'id="due-revision"' in DASHBOARD
    assert 'id="mastery-card"' in DASHBOARD
    assert 'id="mastery-card" class="card half hidden"' in DASHBOARD
    assert "function removeBookmark" not in DASHBOARD


def test_revision_review_has_attempt_owned_question_reporting():
    assert 'result.mode==="revision"' in PRACTICE
    assert 'appendReportControl(box,rows[index].questionId,attemptId)' in PRACTICE
    assert '"/api/me/practice/"+encodeURIComponent(questionId)+"/report"' in PRACTICE
    assert 'attemptId:reportAttemptId' in PRACTICE
    assert 'button.disabled=true' in PRACTICE
    assert "প্রশ্নটি রিপোর্ট করুন" in PRACTICE


def test_practice_errors_are_inline_retryable_and_empty_states_have_actions():
    assert "alert(" not in PRACTICE
    assert 'id="empty-message"' in PRACTICE
    assert 'id="retry"' in PRACTICE
    assert "এতে নকল চেষ্টা তৈরি হবে না" in PRACTICE
    assert 'el("submit").disabled=error.status===409' in PRACTICE
    assert 'el("empty-message").textContent=' in PRACTICE


def test_mini_app_navigation_uses_live_routes_and_marks_revision_active():
    assert 'href="index.html"' not in INDEX
    assert 'href="index.html"' not in DASHBOARD
    assert 'href="index.html"' not in PRACTICE
    assert 'href="index.html"' not in SETTINGS
    assert 'id="nav-quiz" href="./"' in INDEX
    assert 'id="empty-quiz-link" href="./"' in PRACTICE
    assert 'el("page-link").href=quizHomeUrl' in DASHBOARD
    assert 'link.href=quizHomeUrl' in DASHBOARD
    assert 'el("nav-practice").classList.toggle("active",requestedSource!=="due")' in PRACTICE
    assert 'el("nav-revision").classList.toggle("active",requestedSource==="due")' in PRACTICE
    for source in (INDEX, DASHBOARD, PRACTICE, SETTINGS):
        assert "tgWebAppData=" in source
        assert "telegramLaunchHash" in source
        assert "installTelegramNavigation()" in source
        assert "url.hash=telegramLaunchHash" in source.replace(" ", "")
        assert 'href="settings.html"' in source
        assert 'searchParams.set("tgWebAppData"' not in source
        assert "sessionStorage.setItem" not in source.split("telegramLaunchHash", 1)[1].split(
            "function check", 1
        )[0]
    assert 'requestedSection==="analytics"' in DASHBOARD


def test_dashboard_filters_and_leaderboard_pagination_are_wired():
    for control_id in (
        "performance-subject",
        "performance-chapter",
        "performance-days",
        "performance-reset",
        "board-prev",
        "board-next",
        "board-page",
    ):
        assert f'id="{control_id}"' in DASHBOARD
    assert "dashboardData=data;buildPerformanceChapters();applyPerformanceFilters()" in DASHBOARD
    assert '"&offset="+boardOffset' in DASHBOARD
    assert "boardOffset+=boardLimit" in DASHBOARD
    assert "disabled=boardLoading||boardOffset<=0" in DASHBOARD
    assert 'el("board-controls").classList.add("hidden")' in DASHBOARD
    assert 'cache:"no-store"' in DASHBOARD
    assert "privacyRelease=20260801045552" in DASHBOARD
    assert "document.createTextNode(item.displayName" in DASHBOARD
    assert "item.profilePhotoUrl" not in DASHBOARD.split(
        "function boardRow", 1
    )[1].split("function renderYourRank", 1)[0]


def test_every_static_button_and_link_has_a_real_navigation_or_handler_contract():
    for name, source in (
        ("index.html", INDEX),
        ("dashboard.html", DASHBOARD),
        ("practice.html", PRACTICE),
        ("settings.html", SETTINGS),
        ("mock.html", MOCK),
    ):
        for tag in re.findall(r"<button\b[^>]*>", source):
            match = re.search(r'\bid="([^"]+)"', tag)
            if not match:
                classes = re.search(r'\bclass="([^"]+)"', tag)
                assert classes and any(
                    f'querySelector(".{class_name}").addEventListener' in source
                    for class_name in classes.group(1).split()
                ), f"{name} has an unwired template button: {tag}"
                continue
            button_id = match.group(1)
            if 'type="submit"' in tag:
                continue
            assert (
                f'byId("{button_id}").addEventListener' in source
                or f'el("{button_id}").addEventListener' in source
            ), f"{name} button #{button_id} has no click handler"
        for tag in re.findall(r"<a\b[^>]*>", source):
            match = re.search(r'\bhref="([^"]*)"', tag)
            assert match and match.group(1), f"{name} has a link without a destination: {tag}"
            assert not match.group(1).lower().startswith("javascript:")
