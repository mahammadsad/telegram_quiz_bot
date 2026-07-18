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
    assert "bookmark-submit" in INDEX
    assert "result-average" in INDEX
    assert "result-unanswered" in INDEX


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
