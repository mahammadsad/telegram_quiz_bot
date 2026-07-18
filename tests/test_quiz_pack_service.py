from __future__ import annotations

import pytest

from services import quiz_pack_service as service

QUIZ_ID = "20260710-history"


def pack():
    items = []
    for index in range(10):
        items.append({
            "mapping": {"id": f"mapping-{index}", "question_order": index + 1},
            "question": {
                "id": f"question-{index}",
                "question_text": f"বাংলা প্রশ্ন {index}",
                "option_a": "ক", "option_b": "খ", "option_c": "গ", "option_d": "ঘ",
                "correct_option": "ABCD"[index % 4],
                "explanation": "বাংলা ব্যাখ্যা।",
                "detailed_explanation": "বিস্তারিত বাংলা ব্যাখ্যা।",
                "subject": "history",
                "topic": "আধুনিক ভারত",
                "micro_topic_key": "history:modern-india:core",
            },
        })
    return {
        "quiz_id": QUIZ_ID,
        "items": items,
        "meta": {"quiz_id": QUIZ_ID, "subject_key": "history", "chapter": "আধুনিক ভারত"},
    }


def setup_common(monkeypatch):
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: pack())
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})


def test_submission_delegates_one_atomic_rpc(monkeypatch):
    setup_common(monkeypatch)
    calls = []
    expected = {
        "quiz_id": QUIZ_ID, "score": 3, "best_score": 3, "total": 10,
        "answered": 10, "attempt_number": 1, "rank": 1, "participants": 1,
        "review": [],
    }
    monkeypatch.setattr(
        service.quiz_attempts_repo,
        "submit_atomic",
        lambda **kwargs: calls.append(kwargs) or expected,
    )
    result = service.submit_quiz_attempts(
        QUIZ_ID, {"id": 123}, [0] * 10, attempt_id="attempt-1"
    )
    assert result == expected
    assert calls == [{
        "quiz_id": QUIZ_ID,
        "user_id": "user-1",
        "client_attempt_id": "attempt-1",
        "answers": [0] * 10,
        "duration_seconds": None,
        "response_times": None,
        "marked_for_review": None,
    }]


def test_http_retry_keeps_same_client_attempt_id(monkeypatch):
    setup_common(monkeypatch)
    ids = []
    monkeypatch.setattr(
        service.quiz_attempts_repo,
        "submit_atomic",
        lambda **kwargs: ids.append(kwargs["client_attempt_id"]) or {"score": 1},
    )
    service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, "retry-safe-id")
    service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, "retry-safe-id")
    assert ids == ["retry-safe-id", "retry-safe-id"]


@pytest.mark.parametrize("answers", [[0] * 9, [0] * 11, [4] * 10, [True] * 10])
def test_service_defensively_validates_answers(monkeypatch, answers):
    setup_common(monkeypatch)
    with pytest.raises(ValueError):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, answers)


def test_public_quiz_payload_declares_submission_capability():
    payload = service.public_quiz_payload(pack())
    assert payload["capabilities"] == {"submission": True, "source": "api"}
    assert payload["qs"][0]["subjectKey"] == "history"
    assert payload["qs"][0]["chapter"] == "আধুনিক ভারত"
    assert payload["qs"][0]["microTopicKey"] == "history:modern-india:core"
    assert "correct" not in str(payload).lower()


def test_pack_save_uses_one_atomic_rpc_and_preserves_exact_reuse(monkeypatch, valid_questions):
    saved_pack = pack()
    reads = iter([None, saved_pack])
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: next(reads))
    monkeypatch.setattr(
        service.questions_repo,
        "get_by_hash_any_bot",
        lambda *args, **kwargs: {
            "id": "existing-question",
            "subject": "history",
            "topic": "আধুনিক ভারত",
        },
    )
    calls = []
    monkeypatch.setattr(service.quiz_packs_repo, "save_atomic", lambda **kwargs: calls.append(kwargs) or {})
    result = service.record_quiz_pack(
        QUIZ_ID,
        valid_questions,
        {"subject_key": "history", "chapter": "আধুনিক ভারত"},
        worker_id="worker-1",
    )
    assert result is saved_pack
    assert len(calls) == 1 and len(calls[0]["questions"]) == 10
    assert all(row["reuse_question_id"] == "existing-question" for row in calls[0]["questions"])


def test_near_duplicate_is_rejected_instead_of_substituted(monkeypatch, valid_questions):
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: None)
    monkeypatch.setattr(service.questions_repo, "get_by_hash_any_bot", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service.questions_repo,
        "find_similar",
        lambda *args, **kwargs: [{"id": "different-question"}],
    )
    with pytest.raises(Exception, match="Near-duplicate"):
        service.record_quiz_pack(
            QUIZ_ID,
            valid_questions,
            {"subject_key": "history", "chapter": "আধুনিক ভারত"},
            worker_id="worker-1",
        )


def test_question_report_uses_authenticated_user_and_atomic_rpc(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    calls = []
    monkeypatch.setattr(
        service.question_reports_repo,
        "submit",
        lambda **kwargs: calls.append(kwargs) or {"status": "accepted"},
    )
    result = service.submit_question_report(
        question_id="22222222-2222-4222-8222-222222222222",
        quiz_id=QUIZ_ID,
        telegram_user={"id": 123},
        client_attempt_id="attempt-1",
        reason="wrong_answer",
        details="Answer key conflicts with the source.",
    )
    assert result == {"status": "accepted"}
    assert calls[0]["user_id"] == "user-1"
    assert calls[0]["client_attempt_id"] == "attempt-1"


def test_question_report_rejects_unknown_reason(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: pytest.fail("user write"))
    with pytest.raises(ValueError, match="Invalid report reason"):
        service.submit_question_report(
            question_id="22222222-2222-4222-8222-222222222222",
            quiz_id=QUIZ_ID,
            telegram_user={"id": 123},
            client_attempt_id="attempt-1",
            reason="invented",
            details="",
        )
