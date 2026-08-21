from __future__ import annotations

import uuid
from copy import deepcopy

import pytest

from services import quiz_pack_service as service

QUIZ_ID = "20260710-history"
ATTEMPT_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


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


def persisted_pack(rows):
    items = []
    for index, row in enumerate(rows):
        question = {
            "id": f"question-{index}",
            "question_text": row["question"],
            "option_a": row["options"][0],
            "option_b": row["options"][1],
            "option_c": row["options"][2],
            "option_d": row["options"][3],
            "correct_option": "ABCD"[row["correct_index"]],
            "explanation": row["explanation"],
            "detailed_explanation": row["detailed_explanation"],
            "subject": "history",
            "topic": "আধুনিক ভারত",
            **{key: value for key, value in row.items() if key not in {"question", "options", "correct_index"}},
        }
        items.append({"mapping": {"question_order": index + 1}, "question": question})
    return {
        "quiz_id": QUIZ_ID,
        "items": items,
        "meta": {"quiz_id": QUIZ_ID, "subject_key": "history", "chapter": "আধুনিক ভারত"},
    }


def certified_run():
    return {
        "status": "posted",
        "question_count": 10,
        "integrity_verified": True,
        "checksum_contract_version": 2,
        "generated_checksum": "checksum",
        "persisted_checksum": "checksum",
    }


def setup_common(monkeypatch):
    monkeypatch.setattr(service, "get_ready_quiz_pack", lambda quiz_id: pack())
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
        QUIZ_ID, {"id": 123}, [0] * 10, attempt_id=ATTEMPT_ID
    )
    assert result == expected
    assert calls == [{
        "quiz_id": QUIZ_ID,
        "user_id": "user-1",
        "client_attempt_id": ATTEMPT_ID,
        "answers": [0] * 10,
        "client_duration_seconds": None,
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
    service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, ATTEMPT_ID)
    service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, ATTEMPT_ID)
    assert ids == [ATTEMPT_ID, ATTEMPT_ID]


def test_result_recovery_delegates_authenticated_ownership(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: {"id": "user-1"})
    expected = {"score": 8, "review": []}
    calls = []
    monkeypatch.setattr(
        service.quiz_attempts_repo,
        "get_result_for_client",
        lambda **kwargs: calls.append(kwargs) or expected,
    )
    result = service.get_quiz_attempt_result(
        quiz_id=QUIZ_ID,
        telegram_user={"id": 123},
        client_attempt_id=ATTEMPT_ID,
    )
    assert result == expected
    assert calls == [{
        "quiz_id": QUIZ_ID,
        "user_id": "user-1",
        "client_attempt_id": ATTEMPT_ID,
    }]


@pytest.mark.parametrize("answers", [[0] * 9, [0] * 11, [4] * 10, [True] * 10])
def test_service_defensively_validates_answers(monkeypatch, answers):
    setup_common(monkeypatch)
    with pytest.raises(ValueError):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, answers, ATTEMPT_ID)


def test_service_rejects_non_uuid_attempt_id(monkeypatch):
    setup_common(monkeypatch)
    with pytest.raises(ValueError, match="UUID"):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, "unsafe-id")


def test_submission_rejects_an_uncertified_pack_before_user_write(monkeypatch):
    monkeypatch.setattr(service, "get_ready_quiz_pack", lambda quiz_id: None)
    monkeypatch.setattr(
        service.users_repo,
        "upsert_user",
        lambda user: pytest.fail("an uncertified quiz must not create a user or attempt"),
    )
    with pytest.raises(ValueError, match="not ready"):
        service.submit_quiz_attempts(QUIZ_ID, {"id": 123}, [0] * 10, ATTEMPT_ID)


def test_public_quiz_payload_declares_submission_capability():
    payload = service.public_quiz_payload(pack())
    assert payload["capabilities"]["submission"] is True
    assert payload["capabilities"]["source"] == "api"
    assert payload["capabilities"]["marking"] == {
        "rightMarks": 1,
        "wrongPenalty": 0.25,
        "blankMarks": 0,
        "negativeMarking": True,
    }
    assert payload["qs"][0]["subjectKey"] == "history"
    assert payload["qs"][0]["chapter"] == "আধুনিক ভারত"
    assert payload["qs"][0]["microTopicKey"] == "history:modern-india:core"
    assert "correct" not in str(payload).lower()


def test_recent_quizzes_exposes_only_valid_answer_free_metadata(monkeypatch):
    monkeypatch.setattr(
        service.quiz_runs_repo,
        "list_recent_posted",
        lambda **kwargs: [
            {
                "quiz_id": "20260725-history",
                "chapter": "আধুনিক ভারত",
                "posted_at": "2026-07-25T11:30:00+00:00",
            },
            {"quiz_id": "unsafe-id", "chapter": "must be skipped"},
            {"quiz_id": "20260725-history", "chapter": "duplicate"},
            {"quiz_id": "20260725-geography", "chapter": ""},
        ],
    )

    result = service.recent_quizzes(limit=999)

    assert result == {
        "count": 1,
        "items": [
            {
                "quizId": "20260725-history",
                "quizDate": "2026-07-25",
                "subjectKey": "history",
                "subjectName": "ইতিহাস",
                "chapter": "আধুনিক ভারত",
                "postedAt": "2026-07-25T11:30:00+00:00",
            }
        ],
    }


def test_pack_save_uses_one_atomic_rpc_and_preserves_exact_reuse(monkeypatch, valid_questions):
    saved_pack = pack()
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: saved_pack)
    monkeypatch.setattr(
        service.questions_repo,
        "get_by_content_hash",
        lambda *args, **kwargs: {
            "id": "existing-question",
            "subject": "history",
            "topic": "আধুনিক ভারত",
        },
    )
    monkeypatch.setattr(service, "content_checksum", lambda *args, **kwargs: "a" * 64)
    calls = []
    monkeypatch.setattr(
        service.quiz_packs_repo,
        "save_atomic",
        lambda **kwargs: calls.append(kwargs)
        or {
            "ready": True,
            "question_count": 10,
            "generated_checksum": "a" * 64,
            "persisted_checksum": "a" * 64,
        },
    )
    result = service.record_quiz_pack(
        QUIZ_ID,
        valid_questions,
        {"subject_key": "history", "chapter": "আধুনিক ভারত"},
        worker_id="worker-1",
    )
    assert result is saved_pack
    assert len(calls) == 1 and len(calls[0]["questions"]) == 10
    assert all(row["reuse_question_id"] == "existing-question" for row in calls[0]["questions"])


def test_pack_save_preserves_the_grounded_multi_topic_contract(monkeypatch, valid_questions):
    rows = deepcopy(valid_questions)
    source_topics = {}
    distribution = (0, 1, 2, 3, 0, 1, 2, 3, 0, 1)
    for row, index in zip(rows, distribution, strict=True):
        source_id = f"22222222-2222-4222-8222-{index + 1:012d}"
        topic_id = f"11111111-1111-4111-8111-{index + 1:012d}"
        topic_key = f"history:modern-india:topic-{index + 1}"
        row["source_document_id"] = source_id
        row["micro_topic_id"] = topic_id
        row["micro_topic_key"] = topic_key
        source_topics[source_id] = (topic_id, topic_key)

    saved_pack = pack()
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: saved_pack)
    monkeypatch.setattr(
        service.questions_repo,
        "get_by_content_hash",
        lambda *args, **kwargs: {
            "id": "existing-question",
            "subject": "history",
            "topic": "আধুনিক ভারত",
        },
    )
    monkeypatch.setattr(service, "content_checksum", lambda *args, **kwargs: "a" * 64)
    monkeypatch.setattr(
        service.quiz_packs_repo,
        "save_atomic",
        lambda **kwargs: {
            "ready": True,
            "question_count": 10,
            "generated_checksum": "a" * 64,
            "persisted_checksum": "a" * 64,
        },
    )

    result = service.record_quiz_pack(
        QUIZ_ID,
        rows,
        {"subject_key": "history", "chapter": "আধুনিক ভারত"},
        worker_id="worker-1",
        allowed_source_ids=set(source_topics),
        allowed_source_topics=source_topics,
        required_source_diversity=4,
        required_topic_diversity=4,
    )

    assert result is saved_pack


def test_recovery_does_not_infer_a_stricter_diversity_contract(monkeypatch, valid_questions):
    rows = deepcopy(valid_questions)
    distribution = (0, 0, 0, 1, 1, 2, 2, 3, 3, 4)
    for index, (row, group) in enumerate(zip(rows, distribution, strict=True)):
        row["source_document_id"] = f"22222222-2222-4222-8222-{group + 1:012d}"
        row["source_url"] = f"https://ncert.nic.in/history/source-{group}"
        row["micro_topic_id"] = f"11111111-1111-4111-8111-{group + 1:012d}"
        row["micro_topic_key"] = f"history:modern-india:topic-{group}"
        row["correct_index"] = index % 4
    # This pack passed the save-time validator. A later option-quality
    # heuristic rejects short unit-bearing options, but must not make the
    # immutable checksum-certified pack disappear on read.
    rows[4]["question"] = "একজন মন্ত্রী কতদিন পর্যন্ত পদে বহাল থাকতে পারেন?"
    rows[4]["options"] = ["৩ মাস", "৬ মাস", "১ বছর", "২ বছর"]
    rows[4]["correct_index"] = 1
    saved = persisted_pack(rows)
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: saved)
    monkeypatch.setattr(service, "checksum_for_pack", lambda value: "checksum")

    assert service.get_recoverable_quiz_pack(QUIZ_ID, certified_run()) is saved


def test_recovery_accepts_certified_source_less_model_verified_pack(monkeypatch, valid_questions):
    rows = deepcopy(valid_questions)
    for index, row in enumerate(rows):
        row.update({
            "source_document_id": None,
            "source_url": None,
            "source_title": None,
            "source_domain": None,
            "source_kind": None,
            "source_published_at": None,
            "source_accessed_at": None,
            "evidence_summary": None,
            "fact_version": None,
            "knowledge_point_id": f"aaaaaaaa-aaaa-4aaa-8aaa-{index + 1:012d}",
            "micro_topic_id": f"11111111-1111-4111-8111-{index + 1:012d}",
            "micro_topic_key": f"history:modern-india:topic-{index}",
            "verification_status": "verified",
            "review_required": False,
        })
    saved = persisted_pack(rows)
    for index, item in enumerate(saved["items"]):
        question = item["question"]
        question["knowledge_points"] = {
            "id": question["knowledge_point_id"],
            "subject_key": "history",
            "micro_topic_id": question["micro_topic_id"],
            "canonical_claim": f"ঐতিহাসিক দাবি {index}",
            "entity_key": f"entity-{index}",
            "relation_key": "has-answer",
            "answer_value": f"answer-{index}",
            "time_scope": "timeless",
            "syllabus_status": "mapped",
            "status": "active",
        }
        question["question_verifications"] = [{
            "source_document_id": None,
            "verifier_model": "gemini-verifier",
            "verdict": "verified",
            "confidence": 0.95,
            "checks": {"independent_model": True, "source_grounded": False},
            "notes": "Independent verification passed.",
            "checked_at": "2026-08-08T10:00:00+00:00",
            "verification_basis": "independent_model",
        }]
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: saved)
    monkeypatch.setattr(service, "checksum_for_pack", lambda value: "checksum")

    assert service.get_recoverable_quiz_pack(QUIZ_ID, certified_run()) is saved


def test_recovery_rejects_a_mixed_source_contract(monkeypatch, valid_questions):
    rows = deepcopy(valid_questions)
    rows[0]["source_document_id"] = None
    saved = persisted_pack(rows)
    monkeypatch.setattr(service, "get_quiz_pack", lambda quiz_id: saved)
    monkeypatch.setattr(service, "checksum_for_pack", lambda value: "checksum")

    assert service.get_recoverable_quiz_pack(QUIZ_ID, certified_run()) is None


def test_near_duplicate_is_rejected_instead_of_substituted(monkeypatch, valid_questions):
    monkeypatch.setattr(service.questions_repo, "get_by_content_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(service.questions_repo, "get_latest_by_stem", lambda *args, **kwargs: None)
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


def test_database_checksum_mismatch_blocks_pack_before_readback(monkeypatch, valid_questions):
    monkeypatch.setattr(service.questions_repo, "get_by_content_hash", lambda *args: None)
    monkeypatch.setattr(service.questions_repo, "get_latest_by_stem", lambda *args: {"id": "old"})
    monkeypatch.setattr(
        service.quiz_packs_repo,
        "save_atomic",
        lambda **kwargs: {
            "ready": False,
            "question_count": 10,
            "generated_checksum": kwargs["content_checksum"],
            "persisted_checksum": "f" * 64,
        },
    )
    monkeypatch.setattr(
        service,
        "get_quiz_pack",
        lambda quiz_id: pytest.fail("mismatched pack must not be read as ready"),
    )
    with pytest.raises(Exception, match="posting is blocked"):
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
        client_attempt_id=ATTEMPT_ID,
        reason="wrong_answer",
        details="Answer key conflicts with the source.",
    )
    assert result == {"status": "accepted"}
    assert calls[0]["user_id"] == "user-1"
    assert calls[0]["client_attempt_id"] == str(ATTEMPT_ID)


def test_question_report_rejects_unknown_reason(monkeypatch):
    monkeypatch.setattr(service.users_repo, "upsert_user", lambda user: pytest.fail("user write"))
    with pytest.raises(ValueError, match="Invalid report reason"):
        service.submit_question_report(
            question_id="22222222-2222-4222-8222-222222222222",
            quiz_id=QUIZ_ID,
            telegram_user={"id": 123},
            client_attempt_id=ATTEMPT_ID,
            reason="invented",
            details="",
        )
