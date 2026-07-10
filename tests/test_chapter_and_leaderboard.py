from datetime import date, timedelta

from services.chapter_selector import select_chapter
from storage import stats_repo


def test_chapter_selector_prefers_unseen_chapters():
    history = [{"chapter": "প্রাচীন ভারত", "selected_for": "2026-07-09"}]
    assert select_chapter("history", date(2026, 7, 10), history) == "মধ্যযুগীয় ভারত"


def test_chapter_selector_avoids_immediate_repeat_after_catalogue_coverage():
    chapters = ["প্রাচীন ভারত", "মধ্যযুগীয় ভারত", "আধুনিক ভারত", "বাংলার ইতিহাস", "ভারতের জাতীয় আন্দোলন", "গভর্নর জেনারেল ও ভাইসরয়", "সামাজিক-ধর্মীয় সংস্কার আন্দোলন"]
    history = [{"chapter": chapter, "selected_for": (date(2026, 7, 9) - timedelta(days=index)).isoformat()} for index, chapter in enumerate(chapters)]
    assert select_chapter("history", date(2026, 7, 10), history) != "প্রাচীন ভারত"


def test_chapter_selector_uses_due_spaced_review_after_coverage():
    today = date(2026, 7, 10)
    chapters = ["প্রাচীন ভারত", "মধ্যযুগীয় ভারত", "আধুনিক ভারত", "বাংলার ইতিহাস", "ভারতের জাতীয় আন্দোলন", "গভর্নর জেনারেল ও ভাইসরয়", "সামাজিক-ধর্মীয় সংস্কার আন্দোলন"]
    history = [{"chapter": chapter, "selected_for": (today - timedelta(days=20 + index)).isoformat()} for index, chapter in enumerate(chapters)]
    history.insert(0, {"chapter": "প্রাচীন ভারত", "selected_for": (today - timedelta(days=1)).isoformat()})
    history.insert(1, {"chapter": "আধুনিক ভারত", "selected_for": (today - timedelta(days=3)).isoformat()})
    assert select_chapter("history", today, history) == "আধুনিক ভারত"


def test_chapter_selector_never_crosses_subject_catalogues():
    assert select_chapter("science", date(2026, 7, 10), []) == "পদার্থবিদ্যা"
    assert select_chapter("science", date(2026, 7, 10), []) != "প্রাচীন ভারত"


def test_quiz_leaderboard_uses_latest_attempt_then_sorts_score(monkeypatch):
    submissions = [
        {"user_id": "u2", "score": 8, "total": 10, "answered": 10, "completed_at": "2026-07-10T10:02:00Z", "users": {"telegram_id": 2, "first_name": "দুই"}},
        {"user_id": "u1", "score": 10, "total": 10, "answered": 10, "completed_at": "2026-07-10T10:03:00Z", "users": {"telegram_id": 1, "first_name": "এক"}},
        {"user_id": "u3", "score": 8, "total": 10, "answered": 9, "completed_at": "2026-07-10T10:01:00Z", "users": {"telegram_id": 3, "username": "three"}},
        {"user_id": "u3", "score": 7, "total": 10, "answered": 8, "completed_at": "2026-07-10T10:04:00Z", "users": {"telegram_id": 3}},
    ]
    monkeypatch.setattr(stats_repo.submissions_repo, "list_for_quiz", lambda quiz_id, limit: submissions)
    board = stats_repo.quiz_leaderboard("20260710-history")
    assert [row["telegram_user_id"] for row in board["rows"]] == [1, 2, 3]
    assert [row["rank"] for row in board["rows"]] == [1, 2, 3]
    assert [row["attempts_count"] for row in board["rows"]] == [1, 1, 2]
    assert board["rows"][2]["score"] == 7
    assert board["participants"] == 3


def test_quiz_leaderboard_replaces_displayed_score_with_latest_even_when_lower(monkeypatch):
    submissions = [
        {"user_id": "u1", "score": 10, "total": 10, "answered": 10, "completed_at": "2026-07-10T10:00:00Z", "users": {"telegram_id": 1}},
        {"user_id": "u2", "score": 8, "total": 10, "answered": 10, "completed_at": "2026-07-10T10:01:00Z", "users": {"telegram_id": 2}},
        {"user_id": "u1", "score": 6, "total": 10, "answered": 10, "completed_at": "2026-07-10T10:02:00Z", "users": {"telegram_id": 1}},
    ]
    monkeypatch.setattr(stats_repo.submissions_repo, "list_for_quiz", lambda quiz_id, limit: submissions)

    board = stats_repo.quiz_leaderboard("20260710-history")

    assert [row["telegram_user_id"] for row in board["rows"]] == [2, 1]
    assert board["rows"][1]["score"] == 6
    assert board["rows"][1]["attempts_count"] == 2


def test_quiz_leaderboard_limit_does_not_change_participant_count(monkeypatch):
    submissions = [{"user_id": str(i), "score": i, "total": 10, "answered": 10, "completed_at": str(i), "users": {"telegram_id": i}} for i in range(5)]
    monkeypatch.setattr(stats_repo.submissions_repo, "list_for_quiz", lambda quiz_id, limit: submissions)
    board = stats_repo.quiz_leaderboard("20260710-history", limit=2)
    assert len(board["rows"]) == 2 and board["participants"] == 5
