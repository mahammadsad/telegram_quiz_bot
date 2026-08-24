from datetime import date, timedelta

import pytest

from services.quiz_delivery_slo import quiz_delivery_slo_report


def _row(subject: str, *, status: str = "posted", minutes_late: int = 10) -> dict:
    return {
        "logical_date": "2026-08-24",
        "subject_key": subject,
        "due_at": "2026-08-24T03:00:00Z",
        "posted_at": f"2026-08-24T03:{minutes_late:02d}:00Z" if status == "posted" else None,
        "status": status,
    }


def test_slo_counts_expected_missing_late_and_terminal_jobs() -> None:
    rows = [
        _row("history"),
        _row("polity", minutes_late=31),
        _row("geography", status="dead_letter"),
        _row("economics", status="retry_wait"),
    ]

    report = quiz_delivery_slo_report(
        rows, start_date=date(2026, 8, 24), end_date=date(2026, 8, 24)
    )

    assert report["summary"] == {
        "expectedJobs": 13,
        "recordedJobs": 4,
        "postedJobs": 2,
        "onTimeJobs": 1,
        "missingJobs": 9,
        "terminalFailureJobs": 1,
        "retryingJobs": 1,
        "completeDays": 0,
        "deliveryCompletenessRate": round(2 / 13, 6),
        "onTimeDeliveryRate": round(1 / 13, 6),
    }
    assert report["daily"][0]["complete"] is False
    assert "quiz_id" not in str(report).lower()
    assert "telegram" not in str(report).lower()


def test_slo_complete_day_is_recognized() -> None:
    subjects = (
        "history", "polity", "geography", "economics", "science", "current-affairs",
        "english", "bengali", "mathematics", "reasoning", "computer", "environment",
        "miscellaneous",
    )
    report = quiz_delivery_slo_report(
        [_row(subject) for subject in subjects],
        start_date=date(2026, 8, 24),
        end_date=date(2026, 8, 24),
    )
    assert report["summary"]["completeDays"] == 1
    assert report["summary"]["deliveryCompletenessRate"] == 1.0


def test_slo_rejects_duplicate_identity_and_unbounded_windows() -> None:
    duplicate = _row("history")
    with pytest.raises(ValueError, match="duplicate"):
        quiz_delivery_slo_report(
            [duplicate, duplicate],
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 24),
        )
    with pytest.raises(ValueError, match="between 1 and 31"):
        quiz_delivery_slo_report(
            [],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 8, 24),
        )
    with pytest.raises(ValueError, match="grace"):
        quiz_delivery_slo_report(
            [],
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 24),
            on_time_grace=timedelta(hours=7),
        )
