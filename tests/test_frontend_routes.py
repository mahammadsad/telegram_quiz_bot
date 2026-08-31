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
        "/syllabus.html",
        "/privacy.html",
        "/terms.html",
        "/admin.html",
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
        "/syllabus.css": "text/css",
        "/syllabus.js": "text/javascript",
        "/practice.css": "text/css",
        "/practice.js": "text/javascript",
        "/dashboard.css": "text/css",
        "/dashboard.js": "text/javascript",
        "/settings.css": "text/css",
        "/settings.js": "text/javascript",
        "/legal.css": "text/css",
        "/admin.css": "text/css",
        "/admin.js": "text/javascript",
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
    assert CLIENT.get("/syllabus.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/syllabus.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/practice.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/practice.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/dashboard.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/dashboard.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/settings.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/settings.js").headers["cache-control"] == "public, max-age=3600"
    assert CLIENT.get("/legal.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/admin.css").headers["cache-control"] == "public, max-age=300"
    assert CLIENT.get("/admin.js").headers["cache-control"] == "public, max-age=3600"
    source = worker.text
    assert "ANSWER_FREE_NETWORK_TIMEOUT_MS" not in source
    assert "SHELL_NETWORK_TIMEOUT_MS = 30000" in source
    assert "NETWORK_TIMEOUT_MS = 8000" not in source
    assert "new AbortController()" in source
    assert "cache.match(pathname)" in source
    assert "shellNetworkFirst" in source
    assert "client.navigate(client.url)" in source
    assert "tgWebAppData=" in source
    assert "replacesPreviousShell" in source
    assert "await client.navigate" not in source
    assert "cached ||" not in source
    assert "response.status >= 500" in source
    assert 'fetch(request, {cache: "no-store"})' in source

    shell = CLIENT.get("/miniapp-shell.js").text
    assert 'workerUrl.searchParams.set("shell", "8.7.2-ui3")' in shell
    assert 'updateViaCache: "none"' in shell
    assert "registration.update()" in shell


def test_csp_blocks_inline_scripts_and_styles_after_frontend_extraction() -> None:
    csp = CLIENT.get("/settings.html").headers["content-security-policy"]

    assert "script-src 'self' https://telegram.org" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "style-src 'self' https://fonts.googleapis.com" in csp
    assert "style-src 'self' 'unsafe-inline'" not in csp
    for path in ("/index.js", "/practice.js", "/dashboard.js"):
        assert ".style." not in CLIENT.get(path).text


def test_admin_console_is_external_asset_only_and_uses_protected_apis() -> None:
    html = CLIENT.get("/admin.html").text
    script = CLIENT.get("/admin.js").text
    assert '<script src="admin.js"></script>' in html
    assert "<script>" not in html
    assert 'request("/api/admin/operations")' in script
    assert 'request("/api/admin/resources/reviews?limit=50")' in script
    assert 'request("/api/admin/questions/reviews?limit=50")' in script
    assert '"X-Telegram-Init-Data":initData' in script
    assert "innerHTML" not in script


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
    assert 'request("/api/tests/catalog?limit=100")' in script
    assert "window.miniappRequest(api(path)" in script
    assert 'request("/api/tests/attempts/recent?limit=100"' in script
    assert 'request("/api/previous-year?"+pyqParams().toString())' in script
    assert '"X-Telegram-Init-Data":initData' in script
    assert "if(!validTestId(testId)){loadCatalog();return}" in script
    assert 'id="pyq-hierarchy"' in html
    assert "correctIndex" not in script


def test_syllabus_map_is_external_asset_only_and_linked_from_learning_surfaces() -> None:
    html = CLIENT.get("/syllabus.html").text
    script = CLIENT.get("/syllabus.js").text
    assert '<script src="syllabus.js"></script>' in html
    assert "<script>" not in html
    assert "var requestJson=window.miniappRequest" in script
    assert 'requestJson(api("/api/syllabus")' in script
    assert 'api("/api/me/syllabus-progress")' in script
    assert '"X-Telegram-Init-Data":initData' in script
    assert 'id="personal-progress"' in html
    assert "innerHTML" not in script
    assert "syllabus.html" in CLIENT.get("/dashboard.html").text
    assert "syllabus.html" in CLIENT.get("/mock.html").text


def test_public_syllabus_projection_is_answer_free_and_cacheable() -> None:
    response = CLIENT.get("/api/syllabus?exam=WBCS&subject=history")
    assert response.status_code == 200
    assert response.headers["x-answer-free-payload"] == "1"
    assert response.headers["cache-control"].startswith("public, max-age=300")
    assert response.json()["summary"]["subjectCount"] == 1
    assert "correctIndex" not in response.text


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
