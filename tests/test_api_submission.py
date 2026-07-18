from __future__ import annotations

from fastapi.testclient import TestClient

import app as api_module

client = TestClient(api_module.app)
QUIZ_ID = "20260710-history"


def test_valid_submission_contract_is_200_not_422_or_503(monkeypatch):
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123, "first_name": "Test"})
    captured = {}

    def submit(**kwargs):
        captured.update(kwargs)
        return {"quiz_id": QUIZ_ID, "score": 8, "total": 10, "answered": 10, "rank": 1, "participants": 1, "review": []}

    monkeypatch.setattr(api_module.quiz_pack_service, "submit_quiz_attempts", submit)
    response = client.post(
        f"/api/quiz/{QUIZ_ID}/submit",
        json={"initData": "signed", "answers": [0] * 10, "attemptId": "attempt-1"},
    )
    assert response.status_code == 200
    assert captured == {
        "quiz_id": QUIZ_ID,
        "telegram_user": {"id": 123, "first_name": "Test"},
        "answers": [0] * 10,
        "attempt_id": "attempt-1",
        "duration_seconds": None,
        "response_times": None,
        "marked_for_review": None,
    }


def test_submission_carries_learning_signals(monkeypatch):
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    captured = {}
    monkeypatch.setattr(
        api_module.quiz_pack_service,
        "submit_quiz_attempts",
        lambda **kwargs: captured.update(kwargs) or {"score": 7, "total": 10},
    )
    response = client.post(
        f"/api/quiz/{QUIZ_ID}/submit",
        json={
            "initData": "signed",
            "answers": [0] * 10,
            "attemptId": "signals-1",
            "durationSeconds": 312,
            "responseTimes": [31.2] * 10,
            "markedForReview": [False, True] + [False] * 8,
        },
    )
    assert response.status_code == 200
    assert captured["duration_seconds"] == 312
    assert captured["response_times"] == [31.2] * 10
    assert captured["marked_for_review"][1] is True


def test_answer_length_and_values_are_rejected():
    assert client.post(f"/api/quiz/{QUIZ_ID}/submit", json={"initData": "x", "answers": [0] * 9}).status_code == 422
    assert client.post(f"/api/quiz/{QUIZ_ID}/submit", json={"initData": "x", "answers": [0] * 11}).status_code == 422
    assert client.post(f"/api/quiz/{QUIZ_ID}/submit", json={"initData": "x", "answers": [4] * 10}).status_code == 422
    assert client.post(f"/api/quiz/{QUIZ_ID}/submit", json={"initData": "x", "answers": ["1"] * 10}).status_code == 422


def test_production_rejects_unverified_browser_user(monkeypatch):
    monkeypatch.setattr(api_module, "DEV_ALLOW_UNVERIFIED_TELEGRAM", False)
    response = client.post(f"/api/quiz/{QUIZ_ID}/submit", json={"answers": [None] * 10})
    assert response.status_code == 401


def test_public_get_is_read_only_and_has_no_answers(monkeypatch):
    pack = {
        "meta": {"quiz_id": QUIZ_ID, "subject": "ইতিহাস", "chapter": "আধুনিক ভারত"},
        "items": [{"question": {"question_text": f"প্রশ্ন {i}", "option_a": "ক", "option_b": "খ", "option_c": "গ", "option_d": "ঘ", "correct_option": "A", "subject": "history", "topic": "আধুনিক ভারত", "micro_topic_key": "history:modern-india:core"}} for i in range(10)],
    }
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: pack)
    response = client.get(f"/api/quiz/{QUIZ_ID}")
    assert response.status_code == 200
    text = response.text
    assert "correct" not in text and '"a"' not in text
    assert response.json()["qs"][0]["microTopicKey"] == "history:modern-india:core"


def test_quiz_learning_resources_endpoint_requires_live_pack(monkeypatch):
    pack = {"quiz_id": QUIZ_ID, "items": [{}] * 10, "meta": {"quiz_id": QUIZ_ID}}
    expected = {"quizId": QUIZ_ID, "available": False, "topics": [], "policy": {}}
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: pack)
    monkeypatch.setattr(
        api_module.learning_resources_service,
        "public_resources_for_quiz",
        lambda quiz_id: expected,
    )
    response = client.get(f"/api/quiz/{QUIZ_ID}/resources")
    assert response.status_code == 200
    assert response.json() == expected


def test_quiz_learning_resources_endpoint_rejects_static_only_quiz(monkeypatch):
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: None)
    assert client.get(f"/api/quiz/{QUIZ_ID}/resources").status_code == 404


def test_missing_get_returns_404_without_generation(monkeypatch):
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: None)
    monkeypatch.setattr(api_module, "_load_public_fallback", lambda quiz_id: None)
    assert client.get(f"/api/quiz/{QUIZ_ID}").status_code == 404


def test_quiz_specific_leaderboard_endpoint(monkeypatch):
    expected = {"quiz_id": QUIZ_ID, "participants": 1, "rows": [{"rank": 1, "score": 10}]}
    monkeypatch.setattr(api_module.stats_repo, "quiz_leaderboard", lambda quiz_id, limit, offset: expected)
    response = client.get(f"/api/quiz/{QUIZ_ID}/leaderboard")
    assert response.status_code == 200 and response.json() == expected


def test_typed_leaderboard_endpoint_validates_and_delegates(monkeypatch):
    expected = {"type": "subject_accuracy", "participants": 2, "rows": []}
    monkeypatch.setattr(
        api_module.stats_repo,
        "typed_leaderboard",
        lambda board_type, subject_key, limit, offset: expected,
    )
    response = client.get("/api/leaderboards/subject_accuracy?subject=computer&limit=40&offset=3")
    assert response.status_code == 200
    assert response.json() == {**expected, "unavailable": False}
    assert client.get("/api/leaderboards/subject_accuracy?subject=unknown").status_code == 400


def test_health_is_safe_and_never_returns_secret_values(monkeypatch):
    monkeypatch.setattr(api_module, "TELEGRAM_BOT_TOKEN", "super-secret-token")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["quiz_subject_count"] == 13
    assert "super-secret-token" not in response.text
    assert "thread_ids" not in response.text


def test_health_reports_safe_forum_configuration_error(monkeypatch):
    monkeypatch.setattr(api_module, "TELEGRAM_FORUM_TOPICS_JSON", "not-json")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["forum_topics_error"] == "invalid_json"
    assert "not-json" not in response.text


def test_obsolete_submit_payload_class_does_not_exist():
    assert not hasattr(api_module, "SubmitQuizPayload")


def test_static_fallback_is_explicitly_read_only(monkeypatch):
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: None)
    payload = {"meta": {"quiz_id": QUIZ_ID}, "qs": [{"q": str(i), "o": ["a", "b", "c", "d"]} for i in range(10)]}
    monkeypatch.setattr(api_module, "_load_public_fallback", lambda quiz_id: {
        **payload, "capabilities": {"submission": False, "source": "static_fallback"}
    })
    body = client.get(f"/api/quiz/{QUIZ_ID}").json()
    assert body["capabilities"] == {"submission": False, "source": "static_fallback"}


def test_authenticated_question_report_contract(monkeypatch):
    question_id = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123, "first_name": "Test"})
    captured = {}
    monkeypatch.setattr(
        api_module.quiz_pack_service,
        "submit_question_report",
        lambda **kwargs: captured.update(kwargs) or {"status": "accepted"},
    )
    response = client.post(
        f"/api/questions/{question_id}/report",
        json={
            "initData": "signed",
            "quizId": QUIZ_ID,
            "attemptId": "attempt-1",
            "reason": "ambiguous",
            "details": "দুটি বিকল্প একই অর্থ বহন করে।",
        },
    )
    assert response.status_code == 200
    assert captured["question_id"] == question_id
    assert captured["telegram_user"]["id"] == 123
    assert captured["reason"] == "ambiguous"


def test_question_report_rejects_bad_reason_and_unverified_user(monkeypatch):
    question_id = "22222222-2222-4222-8222-222222222222"
    invalid = client.post(
        f"/api/questions/{question_id}/report",
        json={"quizId": QUIZ_ID, "attemptId": "a", "reason": "abuse"},
    )
    assert invalid.status_code == 422
    monkeypatch.setattr(api_module, "DEV_ALLOW_UNVERIFIED_TELEGRAM", False)
    unauthenticated = client.post(
        f"/api/questions/{question_id}/report",
        json={"quizId": QUIZ_ID, "attemptId": "a", "reason": "outdated"},
    )
    assert unauthenticated.status_code == 401
