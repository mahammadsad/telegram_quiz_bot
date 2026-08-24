from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

import app as api_module
from services import syllabus_progress_service
from storage import syllabus_progress_repo

CLIENT = TestClient(api_module.app)


def test_progress_uses_mapped_points_and_strict_mastery_criteria() -> None:
    topics = [
        {"id": "t1", "key": "history:modern-india:t01"},
        {"id": "t2", "key": "history:modern-india:t02"},
    ]
    points = [
        {"id": "p1", "subject_key": "history", "micro_topic_id": "t1"},
        {"id": "p2", "subject_key": "history", "micro_topic_id": "t1"},
        {"id": "p3", "subject_key": "history", "micro_topic_id": "t2"},
        {"id": "foreign", "subject_key": "geography", "micro_topic_id": "t1"},
    ]
    mastery = [
        {"knowledge_point_id": "p1", "attempt_count": 2, "mastery_score": 85, "next_review": "2026-08-24"},
        {"knowledge_point_id": "p2", "attempt_count": 1, "mastery_score": 100, "next_review": "2026-08-25"},
        {"knowledge_point_id": "p3", "attempt_count": 3, "mastery_score": 90, "next_review": None},
    ]
    report = syllabus_progress_service.build_progress(points, topics, mastery, today=date(2026, 8, 24))
    history = next(subject for subject in report["subjects"] if subject["key"] == "history")
    modern = next(chapter for chapter in history["chapters"] if chapter["key"] == "history:modern-india")
    first, second = modern["microTopics"][:2]
    assert first["status"] == "in_progress"
    assert first["mappedKnowledgePoints"] == 2
    assert first["attemptedKnowledgePoints"] == 2
    assert first["masteredKnowledgePoints"] == 1
    assert first["dueKnowledgePoints"] == 1
    assert second["status"] == "mastered"
    assert report["criteria"]["diagnosticClaim"] is False
    assert report["criteria"]["unmappedContentExcludedFromMasteryDenominator"] is True
    serialized = str(report)
    assert "p1" not in serialized
    assert "knowledge_point_id" not in serialized
    assert "mastery_score" not in serialized


def test_unmapped_and_unseen_topics_are_not_claimed_as_complete() -> None:
    report = syllabus_progress_service.build_progress([], [], [], today=date(2026, 8, 24))
    assert report["summary"]["mappedKnowledgePoints"] == 0
    assert report["summary"]["masteryPercent"] == 0.0
    statuses = {
        topic["status"]
        for subject in report["subjects"]
        for chapter in subject["chapters"]
        for topic in chapter["microTopics"]
    }
    assert statuses == {"content_not_mapped"}


def test_progress_endpoint_is_authenticated_and_private(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    monkeypatch.setattr(
        api_module.syllabus_progress_service,
        "syllabus_progress",
        lambda user: {"version": 1, "summary": {"masteryPercent": 12.5}},
    )
    unauthorized = CLIENT.get("/api/me/syllabus-progress")
    assert unauthorized.status_code == 401
    response = CLIENT.get(
        "/api/me/syllabus-progress",
        headers={"X-Telegram-Init-Data": "signed"},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["masteryPercent"] == 12.5
    assert response.headers["cache-control"].startswith("no-store")


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, table, pages, calls):
        self.table = table
        self.pages = pages
        self.calls = calls

    def select(self, fields):
        self.calls.append((self.table, "select", fields))
        return self

    def eq(self, field, value):
        self.calls.append((self.table, "eq", (field, value)))
        return self

    def order(self, field):
        self.calls.append((self.table, "order", field))
        return self

    def range(self, start, end):
        self.calls.append((self.table, "range", (start, end)))
        return self

    def execute(self):
        return Response(self.pages[self.table].pop(0))


class Client:
    def __init__(self, pages, calls):
        self.pages = pages
        self.calls = calls

    def table(self, name):
        return Query(name, self.pages, self.calls)


def test_progress_repository_is_bounded_and_selects_no_content(monkeypatch) -> None:
    calls = []
    pages = {
        "knowledge_points": [[{"id": "p1", "subject_key": "history", "micro_topic_id": "t1"}]],
        "quiz_micro_topics": [[{"id": "t1", "key": "history:modern-india:t01"}]],
        "personal_knowledge_mastery": [[{"knowledge_point_id": "p1", "attempt_count": 1, "mastery_score": 20}]],
    }
    monkeypatch.setattr(syllabus_progress_repo, "get_client", lambda: Client(pages, calls))
    assert len(syllabus_progress_repo.mapped_knowledge_points()) == 1
    assert len(syllabus_progress_repo.micro_topics()) == 1
    assert len(syllabus_progress_repo.user_mastery("user-1")) == 1
    source = " ".join(str(call) for call in calls).lower()
    assert "canonical_claim" not in source
    assert "answer_value" not in source
    assert "question" not in source
    assert all(call[2] == (0, 999) for call in calls if call[1] == "range")
