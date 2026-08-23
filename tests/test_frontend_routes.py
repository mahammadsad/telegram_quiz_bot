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
        "/privacy.html",
        "/terms.html",
    ):
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


def test_pwa_shell_routes_and_cache_boundaries() -> None:
    expected = {
        "/miniapp-shell.css": "text/css",
        "/index.css": "text/css",
        "/index.js": "text/javascript",
        "/mock.css": "text/css",
        "/mock.js": "text/javascript",
        "/practice.css": "text/css",
        "/practice.js": "text/javascript",
        "/dashboard.css": "text/css",
        "/dashboard.js": "text/javascript",
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
    assert CLIENT.get("/miniapp-shell.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/index.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/index.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/mock.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/mock.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/practice.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/practice.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/dashboard.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/dashboard.js").headers["cache-control"] == "public, max-age=3600"
    source = worker.text
    assert "NETWORK_TIMEOUT_MS = 8000" in source
    assert "new AbortController()" in source
    assert "cache.match(pathname)" in source
    assert "response.status >= 500" in source


def test_quiz_intro_uses_citizen_affairs_identity_and_parent_site_cta() -> None:
    html = CLIENT.get("/").text
    assert "Citizen Affairs" in html
    assert "utm_source=telegram" in html
    assert "🌐 Citizen Affairs বাংলা" in html
    assert html.index("🌐 Citizen Affairs বাংলা") < html.index("▶ প্রশ্ন প্রিভিউ")


def test_browser_quiz_preview_does_not_claim_to_save_an_unauthenticated_attempt() -> None:
    html = CLIENT.get("/").text
    assert "স্কোর, র‍্যাঙ্ক ও অগ্রগতি সংরক্ষণ করতে Telegram থেকে কুইজটি খুলুন" in html
    script = CLIENT.get("/index.js").text
    assert "readOnlyMode = legacyLocal || !isTelegram || previewOnly === true" in script
    assert 'readOnlyMode ? "Preview" : "Practice"' in script


def test_mock_page_without_uuid_opens_catalog_instead_of_dead_end() -> None:
    html = CLIENT.get("/mock.html").text
    assert 'id="screen-catalog"' in html
    script = CLIENT.get("/mock.js").text
    assert 'miniappFetch(api("/api/tests/catalog?limit=100"))' in script
    assert "if(!validTestId(testId)){loadCatalog();return}" in script


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
    monkeypatch.setattr(
        api_module.quiz_pack_service,
        "recent_quizzes",
        lambda **kwargs: {"items": [], "count": 0},
    )

    for path in (
        f"/api/tests/instances/{test_id}",
        "/api/quiz/20260808-history",
        "/api/quizzes/recent",
    ):
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert response.headers["x-answer-free-payload"] == "1"
        assert response.headers["cache-control"].startswith("public, max-age=300")
        assert response.headers["etag"].startswith('"')

    assert "X-Answer-Free-Payload" not in CLIENT.get("/health/live").headers


def test_recent_quiz_catalogue_fails_without_leaking_internal_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module.quiz_pack_service,
        "recent_quizzes",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private database detail")),
    )
    response = CLIENT.get("/api/quizzes/recent")
    assert response.status_code == 503
    assert "private database detail" not in response.text
