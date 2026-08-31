from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from storage import content_inventory_repo


class _RecordingQuery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def select(self, fields: str) -> _RecordingQuery:
        self.calls.append(("select", fields))
        return self

    def gte(self, field: str, value: str) -> _RecordingQuery:
        self.calls.append(("gte", (field, value)))
        return self

    def order(self, field: str, *, desc: bool) -> _RecordingQuery:
        self.calls.append(("order", (field, desc)))
        return self

    def limit(self, value: int) -> _RecordingQuery:
        self.calls.append(("limit", value))
        return self

    def execute(self) -> SimpleNamespace:
        self.calls.append(("execute", None))
        return SimpleNamespace(data=[{"event_type": "batch_completed"}])


class _RecordingClient:
    def __init__(self, query: _RecordingQuery) -> None:
        self.query = query
        self.table_name = ""

    def table(self, name: str) -> _RecordingQuery:
        self.table_name = name
        return self.query


def test_recent_replenishment_events_are_bounded_and_answer_free(monkeypatch) -> None:
    query = _RecordingQuery()
    client = _RecordingClient(query)
    monkeypatch.setattr(content_inventory_repo, "get_client", lambda: client)
    since = datetime(2026, 8, 24, tzinfo=timezone.utc)

    rows = content_inventory_repo.list_recent_replenishment_events(
        since=since,
        limit=9000,
    )

    assert rows == [{"event_type": "batch_completed"}]
    assert client.table_name == "content_replenishment_job_events"
    assert query.calls == [
        (
            "select",
            "event_type,accepted_count,rejected_count,rejection_codes,error_code,created_at",
        ),
        ("gte", ("created_at", since.isoformat())),
        ("order", ("created_at", True)),
        ("limit", 5000),
        ("execute", None),
    ]

