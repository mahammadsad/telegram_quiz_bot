from __future__ import annotations

import json

from scripts import report_question_calibration


def test_operator_report_is_aggregate_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(report_question_calibration, "require_env", lambda name: "configured")
    monkeypatch.setattr(report_question_calibration, "supabase_project_ref_matches", lambda: True)
    monkeypatch.setattr(
        report_question_calibration,
        "list_first_attempt_observations",
        lambda **kwargs: [{
            "attempt_id": "private-attempt",
            "question_id": "question-1",
            "user_id": "private-user",
            "completed_at": "2026-08-01T00:00:00+00:00",
            "selected_option": 1,
            "correct_option": 0,
            "is_correct": False,
            "score": 3,
            "total": 10,
            "subject": "history",
            "authored_difficulty": "medium",
        }],
    )
    assert report_question_calibration.main() == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["window_days"] == 90
    assert report["safety"]["aggregate_only"] is True
    assert "private-user" not in output
    assert "private-attempt" not in output
    assert "selected_option" not in output
    assert "correct_option" not in output


def test_operator_report_fails_closed_on_wrong_project(monkeypatch) -> None:
    monkeypatch.setattr(report_question_calibration, "require_env", lambda name: "configured")
    monkeypatch.setattr(report_question_calibration, "supabase_project_ref_matches", lambda: False)
    try:
        report_question_calibration.main()
    except RuntimeError as exc:
        assert str(exc) == "Supabase project ownership check failed."
    else:
        raise AssertionError("expected the ownership guard to fail")
