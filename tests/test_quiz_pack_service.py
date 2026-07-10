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
    monkeypatch.setattr(
        service.submissions_repo,
        "get_by_attempt_id",
        lambda quiz_id, user_id, attempt_id: existing
        if existing and existing.get("client_attempt_id") == attempt_id else None,
    )


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


def test_http_retry_is_idempotent_but_new_attempt_can_improve_score(monkeypatch):
    existing = {"user_id": "user-1", "answers": [0] * 10, "score": 3, "total": 10, "answered": 10, "client_attempt_id": "attempt-1", "completed_at": "2026-07-10T10:00:00Z"}
    setup_common(monkeypatch, existing=existing)
    monkeypatch.setattr(service.submissions_repo, "list_for_quiz", lambda *args, **kwargs: [existing])
    monkeypatch.setattr(service.attempts_repo, "insert_attempt", lambda _: pytest.fail("duplicate wrote an attempt"))
    result = service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, attempt_id="attempt-1")
    assert result["score"] == 3
    assert result["attempt_number"] == 1

    improved_answers = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1]
    improved = {"user_id": "user-1", "answers": improved_answers, "score": 10, "total": 10, "answered": 10, "client_attempt_id": "attempt-2", "completed_at": "2026-07-10T10:05:00Z"}
    monkeypatch.setattr(service.attempts_repo, "insert_attempt", lambda _: None)
    monkeypatch.setattr(service.submissions_repo, "insert", lambda payload: improved)
    monkeypatch.setattr(service.submissions_repo, "list_for_quiz", lambda *args, **kwargs: [existing, improved])
    result = service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, improved_answers, attempt_id="attempt-2")
    assert result["score"] == 10
    assert result["best_score"] == 10
    assert result["attempt_number"] == 2


def test_same_attempt_id_rejects_changed_retry_payload(monkeypatch):
    existing = {"user_id": "user-1", "answers": [0] * 10, "score": 3, "client_attempt_id": "attempt-1"}
    setup_common(monkeypatch, existing=existing)
    with pytest.raises(ValueError, match="identifier"):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [1] * 10, attempt_id="attempt-1")


@pytest.mark.parametrize("answers", [[0] * 9, [0] * 11, [4] * 10, [True] * 10])
def test_service_defensively_validates_answers(monkeypatch, answers):
    setup_common(monkeypatch)
    with pytest.raises(ValueError):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, answers)
