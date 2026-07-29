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
    ):
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
