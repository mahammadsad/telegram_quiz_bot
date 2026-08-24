from __future__ import annotations

from services.question_calibration import CalibrationPolicy, calibration_report


def observation(index: int, *, correct: bool, score: int, selected: int | None = None, **overrides):
    row = {
        "attempt_id": f"attempt-{index}",
        "question_id": "question-1",
        "user_id": f"learner-{index}",
        "completed_at": f"2026-08-01T00:{index % 60:02d}:00+00:00",
        "selected_option": (0 if correct else 1) if selected is None else selected,
        "correct_option": 0,
        "is_correct": correct,
        "score": score,
        "total": 10,
        "subject": "history",
        "authored_difficulty": "medium",
    }
    row.update(overrides)
    return row


def test_report_abstains_below_explicit_sample_gate() -> None:
    rows = [observation(index, correct=index < 8, score=8 if index < 8 else 3) for index in range(10)]
    item = calibration_report(rows)["questions"][0]
    assert item["recommendation"] == "collect_more_data"
    assert item["reason_codes"] == ["minimum_sample_not_met"]
    assert item["facility"] == {
        "estimate": 0.8,
        "wilson_95_lower": 0.4902,
        "wilson_95_upper": 0.9433,
    }


def test_duplicate_learner_question_keeps_earliest_response() -> None:
    rows = [
        observation(1, correct=True, score=8, completed_at="2026-08-02T00:00:00+00:00"),
        observation(2, correct=False, score=2, user_id="learner-1", completed_at="2026-08-01T00:00:00+00:00"),
    ]
    report = calibration_report(rows)
    assert report["coverage"]["usable_first_responses"] == 1
    assert report["coverage"]["discarded_rows"] == 1
    assert report["questions"][0]["facility"]["estimate"] == 0.0


def test_positive_discrimination_and_working_distractors_are_retained() -> None:
    rows = []
    for index in range(60):
        rows.append(observation(index, correct=True, score=9 - index % 2))
    for index in range(60, 100):
        rows.append(observation(index, correct=False, score=2 + index % 2, selected=1 + index % 3))
    item = calibration_report(rows)["questions"][0]
    assert item["recommendation"] == "retain"
    assert item["discrimination"]["point_biserial_rest_score"] > 0.8
    assert item["distractors"]["nonfunctioning_count"] == 0


def test_negative_discrimination_and_dead_distractors_trigger_review() -> None:
    policy = CalibrationPolicy(min_responses=20, min_unique_learners=20, min_group_size=5)
    rows = []
    for index in range(10):
        rows.append(observation(index, correct=True, score=2))
    for index in range(10, 20):
        rows.append(observation(index, correct=False, score=9, selected=1))
    item = calibration_report(rows, policy=policy)["questions"][0]
    assert item["recommendation"] == "editorial_review"
    assert "negative_discrimination" in item["reason_codes"]
    assert "nonfunctioning_distractor" in item["reason_codes"]
    assert item["distractors"]["nonfunctioning_count"] == 2


def test_report_never_exposes_learners_answers_or_answer_key() -> None:
    rows = [observation(index, correct=index % 2 == 0, score=5, selected=index % 4) for index in range(20)]
    serialized = str(calibration_report(rows, policy=CalibrationPolicy(min_responses=20, min_unique_learners=20)))
    assert "learner-" not in serialized
    assert "attempt-" not in serialized
    assert "selected_option" not in serialized
    assert "correct_option" not in serialized
    assert "automatic_retirement': False" in serialized
    assert "automatic_mastery_change': False" in serialized
