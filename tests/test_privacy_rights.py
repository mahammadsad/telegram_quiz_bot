from __future__ import annotations

from fastapi.testclient import TestClient

import app as api_module

CLIENT = TestClient(api_module.app)


def test_data_export_requires_fresh_telegram_auth(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    monkeypatch.setattr(
        api_module.privacy_service,
        "export_my_data",
        lambda user: {"profile": {"telegram_id": user["id"]}, "quizAttempts": []},
    )

    response = CLIENT.post("/api/me/data-export", json={"initData": "signed"})

    assert response.status_code == 200
    assert response.json()["profile"]["telegram_id"] == 123


def test_delete_request_has_grace_period_and_can_be_cancelled(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "verify_init_data", lambda *args: {"id": 123})
    monkeypatch.setattr(
        api_module.privacy_service,
        "request_delete_my_account",
        lambda user: {"requestId": "request-1", "status": "pending", "gracePeriodDays": 7},
    )
    monkeypatch.setattr(
        api_module.privacy_service,
        "cancel_delete_my_account",
        lambda user: {"cancelled": True},
    )

    requested = CLIENT.post("/api/me/account-deletion", json={"initData": "signed"})
    cancelled = CLIENT.post("/api/me/account-deletion/cancel", json={"initData": "signed"})

    assert requested.status_code == 200
    assert requested.json()["gracePeriodDays"] == 7
    assert cancelled.json() == {"cancelled": True}


def test_privacy_pages_are_explicit_legal_drafts() -> None:
    privacy = CLIENT.get("/privacy.html")
    terms = CLIENT.get("/terms.html")

    assert privacy.status_code == 200 and terms.status_code == 200
    assert "OWNER MUST ADD PRIVACY CONTACT" in privacy.text
    assert "OWNER MUST ADD LEGAL ENTITY AND CONTACT" in terms.text
