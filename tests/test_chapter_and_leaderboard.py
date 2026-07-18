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


def test_chapter_selector_keeps_latest_date_for_duplicate_history_rows():
    today = date(2026, 7, 10)
    history = [
        {"chapter": "প্রাচীন ভারত", "selected_for": (today - timedelta(days=1)).isoformat()},
        {"chapter": "আধুনিক ভারত", "selected_for": (today - timedelta(days=2)).isoformat()},
        {"chapter": "মধ্যযুগীয় ভারত", "selected_for": (today - timedelta(days=21)).isoformat()},
        {"chapter": "বাংলার ইতিহাস", "selected_for": (today - timedelta(days=41)).isoformat()},
        {"chapter": "ভারতের জাতীয় আন্দোলন", "selected_for": (today - timedelta(days=51)).isoformat()},
        {"chapter": "গভর্নর জেনারেল ও ভাইসরয়", "selected_for": (today - timedelta(days=61)).isoformat()},
        {"chapter": "সামাজিক-ধর্মীয় সংস্কার আন্দোলন", "selected_for": (today - timedelta(days=71)).isoformat()},
        {"chapter": "আধুনিক ভারত", "selected_for": (today - timedelta(days=200)).isoformat()},
    ]
    assert select_chapter("history", today, history) == "সামাজিক-ধর্মীয় সংস্কার আন্দোলন"
    assert select_chapter("history", today, history) != "আধুনিক ভারত"


def test_chapter_selector_never_crosses_subject_catalogues():
    assert select_chapter("science", date(2026, 7, 10), []) == "পদার্থবিদ্যা"
    assert select_chapter("science", date(2026, 7, 10), []) != "প্রাচীন ভারত"


def test_quiz_leaderboard_uses_paginated_database_rpc(monkeypatch):
    calls = []

    class Result:
        data = {"quiz_id": "20260710-history", "participants": 25000, "rows": []}

    class Client:
        def rpc(self, name, params):
            calls.append((name, params))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(stats_repo, "get_client", Client)
    board = stats_repo.quiz_leaderboard("20260710-history", limit=50, offset=10000)
    assert board["participants"] == 25000
    assert calls == [("get_quiz_leaderboard_page", {
        "p_quiz_id": "20260710-history", "p_limit": 50, "p_offset": 10000,
    })]


def test_global_leaderboard_uses_database_rpc_without_row_cap(monkeypatch):
    calls = []

    class Result:
        data = {"participants": 15000, "rows": []}

    class Client:
        def rpc(self, name, params):
            calls.append((name, params))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(stats_repo, "get_client", Client)
    assert stats_repo.leaderboard(limit=20, offset=12000)["participants"] == 15000
    assert calls[0][0] == "get_global_leaderboard_page"
