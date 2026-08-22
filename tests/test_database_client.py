from __future__ import annotations

import pytest

from database import client as database_client
from errors import ConfigurationError


@pytest.fixture(autouse=True)
def clear_client_cache() -> None:
    database_client.get_client.cache_clear()
    yield
    database_client.get_client.cache_clear()


def test_client_rejects_mismatched_project_before_network_call(monkeypatch) -> None:
    calls: list[tuple[str, str, object]] = []
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://production-ref.supabase.co",
    )
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fake-test-service-key")
    monkeypatch.setenv("EXPECTED_SUPABASE_PROJECT_REF", "staging-ref")
    monkeypatch.setattr(
        database_client,
        "create_client",
        lambda url, key, options: calls.append((url, key, options)),
    )

    with pytest.raises(
        ConfigurationError,
        match="does not match EXPECTED_SUPABASE_PROJECT_REF",
    ):
        database_client.get_client()

    assert calls == []


def test_client_allows_exact_hosted_project_match(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setenv(
        "SUPABASE_URL",
        "https://staging-ref.supabase.co",
    )
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fake-test-service-key")
    monkeypatch.setenv("EXPECTED_SUPABASE_PROJECT_REF", "staging-ref")
    monkeypatch.setattr(
        database_client,
        "create_client",
        lambda url, key, options: sentinel,
    )

    assert database_client.get_client() is sentinel


def test_client_uses_bounded_postgrest_and_storage_timeouts(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("SUPABASE_URL", "https://staging-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fake-test-service-key")
    monkeypatch.setenv("EXPECTED_SUPABASE_PROJECT_REF", "staging-ref")
    monkeypatch.setattr(
        database_client,
        "create_client",
        lambda url, key, options: captured.update({"options": options}) or object(),
    )

    database_client.get_client()

    options = captured["options"]
    assert options.postgrest_client_timeout == database_client.DATABASE_REQUEST_TIMEOUT_SECONDS
    assert options.storage_client_timeout == database_client.DATABASE_REQUEST_TIMEOUT_SECONDS
