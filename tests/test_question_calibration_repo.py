from __future__ import annotations

from datetime import datetime, timezone

from storage import question_calibration_repo


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, pages):
        self.pages = pages
        self.calls: list[tuple[str, object]] = []

    def select(self, value):
        self.calls.append(("select", value))
        return self

    def eq(self, field, value):
        self.calls.append(("eq", (field, value)))
        return self

    def gte(self, field, value):
        self.calls.append(("gte", (field, value)))
        return self

    def order(self, field):
        self.calls.append(("order", field))
        return self

    def range(self, start, end):
        self.calls.append(("range", (start, end)))
        return self

    def execute(self):
        return Response(self.pages.pop(0))


class Client:
    def __init__(self, query):
        self.query = query

    def table(self, name):
        assert name == "quiz_attempt_answers"
        return self.query


def test_repo_filters_first_completed_attempts_and_flattens_relations(monkeypatch) -> None:
    query = Query(
        [[{
            "attempt_id": "a1",
            "question_id": "q1",
            "selected_option": 2,
            "correct_option": 1,
            "is_correct": False,
            "quiz_attempts": {
                "user_id": "u1",
                "score": 4,
                "total": 10,
                "completed_at": "2026-08-01T00:00:00+00:00",
            },
            "questions": {"subject": "history", "difficulty": "hard"},
        }]]
    )
    monkeypatch.setattr(question_calibration_repo, "get_client", lambda: Client(query))
    rows = question_calibration_repo.list_first_attempt_observations(
        since=datetime(2026, 8, 1, tzinfo=timezone.utc),
        max_rows=10,
    )
    assert rows == [{
        "attempt_id": "a1",
        "question_id": "q1",
        "selected_option": 2,
        "correct_option": 1,
        "is_correct": False,
        "user_id": "u1",
        "score": 4,
        "total": 10,
        "completed_at": "2026-08-01T00:00:00+00:00",
        "subject": "history",
        "authored_difficulty": "hard",
    }]
    assert ("eq", ("quiz_attempts.attempt_number", 1)) in query.calls
    assert ("eq", ("quiz_attempts.is_completed", True)) in query.calls
    assert ("range", (0, 9)) in query.calls


def test_repo_never_fetches_more_than_hard_ceiling(monkeypatch) -> None:
    query = Query([[]])
    monkeypatch.setattr(question_calibration_repo, "get_client", lambda: Client(query))
    question_calibration_repo.list_first_attempt_observations(
        since=datetime(2026, 8, 1, tzinfo=timezone.utc),
        max_rows=question_calibration_repo.MAX_ROWS + 1,
    )
    assert ("range", (0, question_calibration_repo.PAGE_SIZE - 1)) in query.calls
