import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
PRACTICE = (ROOT / "practice.html").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "dashboard.html").read_text(encoding="utf-8")


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


def test_personal_dashboard_uses_private_sql_analytics_and_preference_apis():
    assert '"/api/me/dashboard"' in DASHBOARD
    assert '"/api/me/preferences"' in DASHBOARD
    assert '"/api/leaderboards/"' in DASHBOARD
    assert "subjectPerformance" in DASHBOARD
    assert "progressOverTime" in DASHBOARD
    assert 'id="daily-target"' in DASHBOARD
    assert 'id="quiz-mode"' in DASHBOARD
    assert "--tg-theme-bg-color" in DASHBOARD
    assert "prefers-reduced-motion" in DASHBOARD
    assert '"miscellaneous":"বিবিধ সাধারণ জ্ঞান"' in DASHBOARD
    assert '"static-gk"' not in DASHBOARD


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
        'id="revision-sound"',
        'id="revision-vibration"',
        'id="test-sound"',
        'localPreference("revisionSoundEnabled"',
        '<option value="overall_rank">সামগ্রিক র‍্যাঙ্ক</option>',
    ):
        assert contract in DASHBOARD
    assert 'id="weak-practice"' in DASHBOARD
    assert 'source=weak_topic&subject=' in DASHBOARD
    assert 'el("page-title").textContent="কুইজ ড্যাশবোর্ড"' in DASHBOARD
    assert 'el("page-link").textContent="আমার ড্যাশবোর্ড"' in DASHBOARD
    assert 'id="bookmarks-card"' in DASHBOARD
    assert 'id="r-overdue"' in DASHBOARD
    assert 'id="revision-subjects"' in DASHBOARD
    assert "function removeBookmark" in DASHBOARD
    assert "active:false" in DASHBOARD


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


def test_every_static_button_and_link_has_a_real_navigation_or_handler_contract():
    for name, source in (
        ("index.html", INDEX),
        ("dashboard.html", DASHBOARD),
        ("practice.html", PRACTICE),
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
