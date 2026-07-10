from __future__ import annotations

from copy import deepcopy

import pytest

from services import quiz_pack_service as service


QUIZ_ID = "20260710-history"


def pack():
    items = []
    for index in range(10):
        items.append({
            "poll": {"id": f"poll-{index}"},
            "question": {
                "id": f"question-{index}",
                "question_text": f"বাংলা প্রশ্ন {index}",
                "option_a": "ক", "option_b": "খ", "option_c": "গ", "option_d": "ঘ",
                "correct_option": "ABCD"[index % 4],
                "explanation": "বাংলা ব্যাখ্যা।",
                "detailed_explanation": "বিস্তারিত বাংলা ব্যাখ্যা।",
            },
        })
    return {"quiz_id": QUIZ_ID, "items": items, "meta": {"quiz_id": QUIZ_ID}}


def setup_common(monkeypatch, existing=None):
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: pack())
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    monkeypatch.setattr(service.submissions_repo, "get", lambda quiz_id, user_id: existing)
    monkeypatch.setattr(service.stats_repo, "quiz_leaderboard", lambda quiz_id, limit: {"participants": 1, "rows": []})


def test_score_calculated_server_side_and_attempts_stored(monkeypatch):
    setup_common(monkeypatch)
    inserted_attempts = []
    monkeypatch.setattr(service.attempts_repo, "insert_attempt", inserted_attempts.append)
    submission = {"user_id": "user-1", "answers": [0] * 10, "score": 3, "total": 10, "answered": 10, "completed_at": "2026-07-10T00:00:00Z"}
    monkeypatch.setattr(service.submissions_repo, "insert", lambda payload: {**payload, "user_id": "user-1", "completed_at": submission["completed_at"]})
    monkeypatch.setattr(service.submissions_repo, "list_for_quiz", lambda *args, **kwargs: [submission])
    result = service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10)
    assert result["score"] == 3
    assert result["answered"] == 10
    assert len(inserted_attempts) == 10


def test_unanswered_are_preserved_and_not_inserted_as_attempts(monkeypatch):
    setup_common(monkeypatch)
    inserted_attempts = []
    monkeypatch.setattr(service.attempts_repo, "insert_attempt", inserted_attempts.append)
    answers = [None] * 10
    monkeypatch.setattr(service.submissions_repo, "insert", lambda payload: {**payload, "user_id": "user-1", "completed_at": "now"})
    monkeypatch.setattr(service.submissions_repo, "list_for_quiz", lambda *args, **kwargs: [{"user_id": "user-1", "score": 0, "completed_at": "now"}])
    result = service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, answers)
    assert result["answered"] == 0 and inserted_attempts == []


def test_identical_duplicate_is_idempotent_and_conflict_is_immutable(monkeypatch):
    existing = {"user_id": "user-1", "answers": [0] * 10, "score": 3, "total": 10, "answered": 10, "completed_at": "now"}
    setup_common(monkeypatch, existing=existing)
    monkeypatch.setattr(service.submissions_repo, "list_for_quiz", lambda *args, **kwargs: [existing])
    monkeypatch.setattr(service.attempts_repo, "insert_attempt", lambda _: pytest.fail("duplicate wrote an attempt"))
    result = service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10)
    assert result["score"] == 3
    with pytest.raises(ValueError, match="immutable"):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [1] * 10)


@pytest.mark.parametrize("answers", [[0] * 9, [0] * 11, [4] * 10, [True] * 10])
def test_service_defensively_validates_answers(monkeypatch, answers):
    setup_common(monkeypatch)
    with pytest.raises(ValueError):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, answers)
