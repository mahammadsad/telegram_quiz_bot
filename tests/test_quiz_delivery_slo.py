from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from services import quiz_delivery_slo
from services.quiz_delivery_slo import latest_closed_delivery_date, quiz_delivery_slo_report


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
        "terminalFailureRate": round(1 / 13, 6),
    }
    assert report["objectives"]["policyVersion"] == 1
    assert report["evaluation"]["overallMet"] is False
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
    assert report["evaluation"] == {
        "deliveryCompletenessMet": True,
        "onTimeDeliveryMet": True,
        "missingJobsMet": True,
        "terminalFailureRateMet": True,
        "unknownDeliveryMet": True,
        "overallMet": True,
    }


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


@pytest.mark.parametrize(("clock", "expected"), [
    ("2026-09-06T01:18:00+00:00", "2026-09-05"),
    ("2026-09-06T13:59:59+00:00", "2026-09-05"),
    ("2026-09-06T14:00:00+00:00", "2026-09-06"),
    ("2026-09-06T19:30:00+05:30", "2026-09-06"),
    ("2026-09-06T18:30:00+00:00", "2026-09-06"),
    ("2026-01-01T00:00:00+05:30", "2025-12-31"),
])
def test_default_slo_window_closes_after_last_ist_slot_and_grace(clock, expected):
    assert latest_closed_delivery_date(datetime.fromisoformat(clock)) == date.fromisoformat(expected)


def test_report_close_tracks_schedule_changes_across_midnight(monkeypatch):
    late_subject = replace(quiz_delivery_slo.QUIZ_SUBJECTS[-1], scheduled_time_ist="23:50")
    monkeypatch.setattr(quiz_delivery_slo, "QUIZ_SUBJECTS", (late_subject,))
    assert latest_closed_delivery_date(datetime.fromisoformat("2026-09-06T00:19:59+05:30")) == date(2026, 9, 4)
    assert latest_closed_delivery_date(datetime.fromisoformat("2026-09-06T00:20:00+05:30")) == date(2026, 9, 5)
    with pytest.raises(ValueError, match="timezone-aware"):
        latest_closed_delivery_date(datetime(2026, 9, 6))


@pytest.mark.parametrize(("extra_args", "expected_end"), [
    ([], "2026-09-05"), (["--end-date", "2026-09-03"], "2026-09-03"),
])
def test_slo_cli_uses_closed_window_but_preserves_explicit_end_date(monkeypatch, capsys, extra_args, expected_end):
    from scripts import report_quiz_delivery_slo as script

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 6, 1, 18, tzinfo=timezone.utc)

    queried = []
    monkeypatch.setattr(script, "datetime", Clock)
    monkeypatch.setattr(script.sys, "argv", ["report", "--days", "5", *extra_args])
    monkeypatch.setattr(script, "require_env", lambda _name: None)
    monkeypatch.setattr(script, "supabase_project_ref_matches", lambda: True)
    monkeypatch.setattr(script.quiz_jobs_repo, "list_delivery_slo_window", lambda start, end: queried.append((start, end)) or [])
    assert script.main() == 0
    expected_start = (date.fromisoformat(expected_end) - timedelta(days=4)).isoformat()
    assert queried == [(expected_start, expected_end)]
    assert f'"end": "{expected_end}"' in capsys.readouterr().out
