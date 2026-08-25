from __future__ import annotations

import httpx
import pytest

from scripts import report_question_inventory


def test_inventory_report_retries_transient_read_transport(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> list[str]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("temporary read timeout")
        return ["ready"]

    monkeypatch.setattr(report_question_inventory.time, "sleep", delays.append)

    assert report_question_inventory._read_with_retry(operation) == ["ready"]
    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_inventory_report_does_not_retry_non_transport_error(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(report_question_inventory.time, "sleep", sleeps.append)

    with pytest.raises(ValueError, match="contract failure"):
        report_question_inventory._read_with_retry(
            lambda: (_ for _ in ()).throw(ValueError("contract failure"))
        )

    assert sleeps == []
