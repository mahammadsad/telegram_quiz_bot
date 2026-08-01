from datetime import date, timedelta

from services import chapter_selector
from services.chapter_selector import select_chapter
from storage import chapter_history_repo, stats_repo


def test_chapter_selector_prefers_unseen_chapters():
    history = [{"chapter": "প্রাচীন ভারত", "selected_for": "2026-07-09"}]
    assert select_chapter("history", date(2026, 7, 10), history) == "ভারতের জাতীয় আন্দোলন"


def test_chapter_selector_avoids_immediate_repeat_after_catalogue_coverage():
    chapters = ["প্রাচীন ভারত", "মধ্যযুগীয় ভারত", "আধুনিক ভারত", "বাংলার ইতিহাস", "ভারতের জাতীয় আন্দোলন", "গভর্নর জেনারেল ও ভাইসরয়", "সামাজিক-ধর্মীয় সংস্কার আন্দোলন"]
    history = [{"chapter": chapter, "selected_for": (date(2026, 7, 9) - timedelta(days=index)).isoformat()} for index, chapter in enumerate(chapters)]
    assert select_chapter("history", date(2026, 7, 10), history) != "প্রাচীন ভারত"


def test_chapter_selector_uses_due_spaced_review_after_coverage(monkeypatch):
    today = date(2026, 7, 10)
    chapters = ["প্রাচীন ভারত", "মধ্যযুগীয় ভারত", "আধুনিক ভারত", "বাংলার ইতিহাস", "ভারতের জাতীয় আন্দোলন", "গভর্নর জেনারেল ও ভাইসরয়", "সামাজিক-ধর্মীয় সংস্কার আন্দোলন"]
    monkeypatch.setitem(chapter_selector.CHAPTERS, "history", tuple(chapters))
    history = [{"chapter": chapter, "selected_for": (today - timedelta(days=20 + index)).isoformat()} for index, chapter in enumerate(chapters)]
    history.insert(0, {"chapter": "প্রাচীন ভারত", "selected_for": (today - timedelta(days=1)).isoformat()})
    history.insert(1, {"chapter": "আধুনিক ভারত", "selected_for": (today - timedelta(days=3)).isoformat()})
    assert select_chapter("history", today, history) == "আধুনিক ভারত"


def test_chapter_selector_ignores_legacy_history_outside_runtime_catalogue(monkeypatch):
    today = date(2026, 7, 28)
    approved = ("ব্যাংকিং ও RBI", "মুদ্রাস্ফীতি")
    monkeypatch.setitem(chapter_selector.CHAPTERS, "economics", approved)
    history = [
        {"chapter": approved[0], "selected_for": (today - timedelta(days=1)).isoformat()},
        {"chapter": approved[1], "selected_for": (today - timedelta(days=20)).isoformat()},
        {"chapter": "কেন্দ্রীয় বাজেট", "selected_for": (today - timedelta(days=3)).isoformat()},
    ]

    assert select_chapter("economics", today, history) == approved[1]
    assert select_chapter("economics", today, history) in approved


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
    assert select_chapter("history", today, history) == "ভারতের জাতীয় আন্দোলন"
    assert select_chapter("history", today, history) != "প্রাচীন ভারত"


def test_chapter_selector_never_crosses_subject_catalogues():
    assert select_chapter("science", date(2026, 7, 10), []) == "পরিমাপ, গতি ও যান্ত্রিকী"
    assert select_chapter("science", date(2026, 7, 10), []) != "প্রাচীন ভারত"


def test_chapter_history_record_updates_legacy_table_without_unique_constraint(
    monkeypatch,
):
    calls = []

    class Result:
        def __init__(self, data):
            self.data = data

    class Query:
        def __init__(self, existing):
            self.existing = existing
            self.action = ""
            self.payload = None
            self.filters = []

        def select(self, fields):
            self.action = "select"
            return self

        def update(self, payload):
            self.action = "update"
            self.payload = payload
            return self

        def insert(self, payload):
            self.action = "insert"
            self.payload = payload
            return self

        def eq(self, field, value):
            self.filters.append((field, value))
            return self

        def limit(self, value):
            return self

        def execute(self):
            calls.append((self.action, self.payload, self.filters))
            return Result([{"id": "existing"}] if self.action == "select" and self.existing else [])

    class Client:
        def __init__(self, existing):
            self.existing = existing

        def table(self, name):
            assert name == "chapter_history"
            return Query(self.existing)

    monkeypatch.setattr(chapter_history_repo, "get_client", lambda: Client(True))
    chapter_history_repo.record(
        "computer",
        "কম্পিউটার মৌলিক ধারণা",
        "2026-07-27",
        "20260727-computer",
    )

    assert [call[0] for call in calls] == ["select", "update"]
    assert ("subject_key", "computer") in calls[1][2]
    assert ("selected_for", "2026-07-27") in calls[1][2]


def test_chapter_history_record_inserts_when_date_is_new(monkeypatch):
    calls = []

    class Result:
        def __init__(self, data):
            self.data = data

    class Query:
        def __init__(self):
            self.action = ""
            self.payload = None

        def select(self, fields):
            self.action = "select"
            return self

        def insert(self, payload):
            self.action = "insert"
            self.payload = payload
            return self

        def eq(self, field, value):
            return self

        def limit(self, value):
            return self

        def execute(self):
            calls.append((self.action, self.payload))
            return Result([])

    class Client:
        def table(self, name):
            assert name == "chapter_history"
            return Query()

    monkeypatch.setattr(chapter_history_repo, "get_client", Client)
    chapter_history_repo.record(
        "computer",
        "কম্পিউটার মৌলিক ধারণা",
        "2026-07-27",
        "20260727-computer",
    )

    assert [call[0] for call in calls] == ["select", "insert"]
    assert calls[1][1]["quiz_id"] == "20260727-computer"


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


def test_typed_leaderboard_uses_bounded_database_rpc(monkeypatch):
    calls = []

    class Result:
        data = {"type": "weekly_accuracy", "participants": 32000, "rows": []}

    class Client:
        def rpc(self, name, params):
            calls.append((name, params))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(stats_repo, "get_client", Client)
    board = stats_repo.typed_leaderboard(
        "weekly_accuracy",
        subject_key=None,
        limit=50,
        offset=20000,
    )
    assert board["participants"] == 32000
    assert calls == [(
        "get_leaderboard_page",
        {
            "p_type": "weekly_accuracy",
            "p_subject_key": None,
            "p_limit": 50,
            "p_offset": 20000,
        },
    )]


def test_typed_leaderboard_rejects_unknown_or_subjectless_type():
    import pytest

    with pytest.raises(ValueError, match="Unknown leaderboard"):
        stats_repo.typed_leaderboard("volume", subject_key=None)
    with pytest.raises(ValueError, match="requires a subject"):
        stats_repo.typed_leaderboard("subject_accuracy", subject_key=None)


def test_current_user_typed_leaderboard_uses_exact_rpc(monkeypatch):
    calls = []

    class Result:
        data = {"participants": 101, "rows": [], "currentUser": {"rank": 101}}

    class Client:
        def rpc(self, name, payload):
            calls.append((name, payload))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(stats_repo, "get_client", lambda: Client())
    board = stats_repo.typed_leaderboard_for_user(
        "weekly_accuracy",
        subject_key=None,
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        limit=10,
        offset=0,
    )
    assert board["currentUser"]["rank"] == 101
    assert calls == [
        (
            "get_leaderboard_for_user",
            {
                "p_type": "weekly_accuracy",
                "p_subject_key": None,
                "p_user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "p_limit": 10,
                "p_offset": 0,
            },
        )
    ]


def test_current_user_quiz_leaderboard_uses_offset_aware_privacy_rpc(monkeypatch):
    calls = []

    class Result:
        data = {
            "participants": 101,
            "rows": [],
            "currentUser": {"rank": 101},
        }

    class Client:
        def rpc(self, name, payload):
            calls.append((name, payload))
            return self

        def execute(self):
            return Result()

    monkeypatch.setattr(stats_repo, "get_client", lambda: Client())
    board = stats_repo.quiz_leaderboard_for_user(
        "20260710-history",
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        limit=10,
        offset=20,
    )
    assert board["currentUser"]["rank"] == 101
    assert calls == [
        (
            "get_quiz_leaderboard_for_user_page",
            {
                "p_quiz_id": "20260710-history",
                "p_user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "p_limit": 10,
                "p_offset": 20,
            },
        )
    ]
