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
    response = client.post(f"/api/quiz/{QUIZ_ID}/submit", json={"initData": "signed", "answers": [0] * 10})
    assert response.status_code == 200
    assert captured == {"quiz_id": QUIZ_ID, "telegram_user": {"id": 123, "first_name": "Test"}, "answers": [0] * 10}


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
        "items": [{"question": {"question_text": f"প্রশ্ন {i}", "option_a": "ক", "option_b": "খ", "option_c": "গ", "option_d": "ঘ", "correct_option": "A"}} for i in range(10)],
    }
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: pack)
    response = client.get(f"/api/quiz/{QUIZ_ID}")
    assert response.status_code == 200
    text = response.text
    assert "correct" not in text and '"a"' not in text


def test_missing_get_returns_404_without_generation(monkeypatch):
    monkeypatch.setattr(api_module.quiz_pack_service, "get_quiz_pack", lambda quiz_id: None)
    monkeypatch.setattr(api_module, "_load_public_fallback", lambda quiz_id: None)
    assert client.get(f"/api/quiz/{QUIZ_ID}").status_code == 404


def test_quiz_specific_leaderboard_endpoint(monkeypatch):
    expected = {"quiz_id": QUIZ_ID, "participants": 1, "rows": [{"rank": 1, "score": 10}]}
    monkeypatch.setattr(api_module.stats_repo, "quiz_leaderboard", lambda quiz_id, limit: expected)
    response = client.get(f"/api/quiz/{QUIZ_ID}/leaderboard")
    assert response.status_code == 200 and response.json() == expected


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
