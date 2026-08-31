import json
import logging
import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import app as api_module
from database.observability import database_timing

CLIENT = TestClient(api_module.app)


def _request_records(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "app.http" and '"event":"http_request"' in record.getMessage()
    ]


def test_response_echoes_only_valid_request_ids_and_reports_total_app_timing() -> None:
    valid_request_id = "trace-ABC_123:edge.4"
    response = CLIENT.get("/health/live", headers={"X-Request-ID": valid_request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == valid_request_id
    assert re.fullmatch(r"app;dur=\d+\.\d{2}", response.headers["server-timing"])

    generated = CLIENT.get("/health/live", headers={"X-Request-ID": "not valid"})
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["x-request-id"])
    assert generated.headers["x-request-id"] != "not valid"


def test_validated_request_id_is_available_to_route_handlers() -> None:
    async def request_state_probe(request: Request) -> dict[str, str]:
        return {"requestId": request.state.request_id}

    api_module.app.add_api_route(
        "/__tests__/request-state-probe",
        request_state_probe,
        methods=["GET"],
        include_in_schema=False,
    )
    test_route = api_module.app.router.routes[-1]
    try:
        response = CLIENT.get(
            "/__tests__/request-state-probe",
            headers={"X-Request-ID": "state-probe-id"},
        )
    finally:
        api_module.app.router.routes.remove(test_route)

    assert response.status_code == 200
    assert response.json() == {"requestId": "state-probe-id"}
    assert response.headers["x-request-id"] == "state-probe-id"


def test_database_timings_are_correlated_without_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_payload = "private-telegram-init-data"

    async def database_timing_probe() -> dict[str, bool]:
        with database_timing("personal.dashboard_bootstrap"):
            return {"ok": True}

    api_module.app.add_api_route(
        "/__tests__/database-timing-probe",
        database_timing_probe,
        methods=["GET"],
        include_in_schema=False,
    )
    test_route = api_module.app.router.routes[-1]
    try:
        caplog.set_level(logging.INFO, logger="app.http")
        response = CLIENT.get(
            f"/__tests__/database-timing-probe?private={private_payload}",
            headers={"X-Request-ID": "database-timing-id"},
        )
    finally:
        api_module.app.router.routes.remove(test_route)

    assert response.status_code == 200
    assert re.fullmatch(
        r"app;dur=\d+\.\d{2}, db;dur=\d+\.\d{2}",
        response.headers["server-timing"],
    )
    record = _request_records(caplog)[-1]
    assert record["request_id"] == "database-timing-id"
    assert record["database_duration_ms"] >= 0
    assert len(record["database_operations"]) == 1
    assert record["database_operations"][0]["label"] == "personal.dashboard_bootstrap"
    assert record["database_operations"][0]["duration_ms"] >= 0
    assert private_payload not in json.dumps(record)


def test_log_uses_route_template_and_excludes_url_and_private_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.http")
    private_question_id = "22222222-2222-4222-8222-222222222222"
    private_query_value = "private-init-data-value"

    response = CLIENT.post(
        f"/api/questions/{private_question_id}/report?initData={private_query_value}",
        json={},
        headers={"X-Request-ID": "safe-correlation-id"},
    )

    assert response.status_code == 422
    records = _request_records(caplog)
    assert records[-1]["route"] == "/api/questions/{question_id}/report"
    assert records[-1]["method"] == "POST"
    assert records[-1]["status"] == 422
    assert records[-1]["outcome"] == "complete"
    assert records[-1]["request_id"] == "safe-correlation-id"
    assert records[-1]["duration_ms"] >= 0
    rendered = json.dumps(records[-1])
    assert private_question_id not in rendered
    assert private_query_value not in rendered
    assert "initData" not in rendered


def test_unmatched_route_is_logged_without_echoing_the_raw_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.http")
    private_path_value = "33333333-3333-4333-8333-333333333333"

    response = CLIENT.get(f"/missing/{private_path_value}")

    assert response.status_code == 404
    assert response.headers["x-request-id"]
    record = _request_records(caplog)[-1]
    assert record["route"] == "<unmatched>"
    assert private_path_value not in json.dumps(record)


def test_unhandled_failure_keeps_fastapi_exception_behavior_and_safe_observability(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_exception_detail = "private-database-payload"

    async def fail_unhandled() -> None:
        raise RuntimeError(private_exception_detail)

    api_module.app.add_api_route(
        "/__tests__/unhandled-observability",
        fail_unhandled,
        methods=["GET"],
        include_in_schema=False,
    )
    test_route = api_module.app.router.routes[-1]
    try:
        raising_client = TestClient(api_module.app)
        with pytest.raises(RuntimeError, match=private_exception_detail):
            raising_client.get("/__tests__/unhandled-observability")

        caplog.clear()
        caplog.set_level(logging.INFO, logger="app.http")
        response = TestClient(api_module.app, raise_server_exceptions=False).get(
            "/__tests__/unhandled-observability",
            headers={"X-Request-ID": "failed-request-id"},
        )
    finally:
        api_module.app.router.routes.remove(test_route)

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["x-request-id"] == "failed-request-id"
    assert re.fullmatch(r"app;dur=\d+\.\d{2}", response.headers["server-timing"])
    records = _request_records(caplog)
    assert len(records) == 1
    assert records[0]["route"] == "/__tests__/unhandled-observability"
    assert records[0]["status"] == 500
    assert records[0]["outcome"] == "unhandled_exception"
    assert private_exception_detail not in json.dumps(records[0])
