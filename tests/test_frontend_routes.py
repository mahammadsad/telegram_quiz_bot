import uuid

from fastapi.testclient import TestClient

import app as api_module

CLIENT = TestClient(api_module.app)


def test_frontend_routes_include_index_alias_for_cached_mini_apps() -> None:
    for path in (
        "/",
        "/index.html",
        "/dashboard.html",
        "/practice.html",
        "/settings.html",
        "/mock.html",
    ):
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


def test_pwa_shell_routes_and_cache_boundaries() -> None:
    expected = {
        "/miniapp-shell.js": "text/javascript",
        "/service-worker.js": "text/javascript",
        "/manifest.webmanifest": "application/manifest+json",
        "/pwa-icon.svg": "image/svg+xml",
    }
    for path, content_type in expected.items():
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)
    worker = CLIENT.get("/service-worker.js")
    assert worker.headers["cache-control"] == "no-cache, max-age=0"
    assert worker.headers["service-worker-allowed"] == "/"


def test_only_answer_free_pre_submission_projections_are_cache_eligible(monkeypatch) -> None:
    test_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr(
        api_module.exam_config_service,
        "public_test_instance",
        lambda value: {"testInstanceId": str(value), "sections": []},
    )
    monkeypatch.setattr(
        api_module.quiz_pack_service,
        "get_ready_quiz_pack",
        lambda quiz_id: {"items": [{}] * 10},
    )
    monkeypatch.setattr(
        api_module.quiz_pack_service,
        "public_quiz_payload",
        lambda pack: {"qs": [{"q": "safe", "o": ["A", "B", "C", "D"]}] * 10},
    )

    for path in (f"/api/tests/instances/{test_id}", "/api/quiz/20260808-history"):
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert response.headers["x-answer-free-payload"] == "1"
        assert response.headers["cache-control"] == "private, no-cache, max-age=0"

    assert "X-Answer-Free-Payload" not in CLIENT.get("/health/live").headers
