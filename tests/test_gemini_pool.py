from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.gemini_provider_pool import (
    GeminiGenerationError,
    GeminiProviderPool,
    KEY_FAILURE,
    MODEL_UNAVAILABLE,
    NON_RETRYABLE,
    SAFETY_BLOCK,
    TRANSIENT,
)


class ApiError(Exception):
    def __init__(self, status_code, message="failure"):
        super().__init__(message)
        self.status_code = status_code


class Models:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


class Client:
    def __init__(self, outcomes):
        self.models = Models(outcomes)


def make_pool(primary, secondary, **extra):
    clients = {"primary-secret": Client(primary), "secondary-secret": Client(secondary)}
    env = {
        "GEMINI_API_KEY_PRIMARY": "primary-secret",
        "GEMINI_API_KEY_SECONDARY": "secondary-secret",
        "GEMINI_MAX_ATTEMPTS_PER_KEY": "2",
        "GEMINI_BACKOFF_BASE_SECONDS": "0",
        "GEMINI_MAX_BACKOFF_SECONDS": "0",
        **extra,
    }
    pool = GeminiProviderPool(environ=env, client_factory=lambda key: clients[key], sleep=lambda _: None, jitter=lambda: 0)
    return pool, clients


def generate(pool):
    return pool.generate_subject_quiz(prompt="safe prompt", response_schema={"type": "ARRAY"})


def test_primary_success_never_calls_secondary():
    pool, clients = make_pool(["[]"], ["unused"])
    text, metadata = generate(pool)
    assert text == "[]" and metadata["provider"] == "primary"
    assert len(clients["secondary-secret"].models.calls) == 0


@pytest.mark.parametrize("error", [ApiError(429, "RESOURCE_EXHAUSTED"), ApiError(503), TimeoutError("socket timeout")])
def test_transient_primary_twice_then_secondary_succeeds(error):
    pool, clients = make_pool([error, error], ["[]"])
    _, metadata = generate(pool)
    assert metadata["provider"] == "secondary"
    assert len(clients["primary-secret"].models.calls) == 2
    assert len(clients["secondary-secret"].models.calls) == 1


def test_invalid_primary_key_immediately_uses_secondary():
    pool, clients = make_pool([ApiError(401, "invalid api key")], ["[]"])
    _, metadata = generate(pool)
    assert metadata["provider"] == "secondary"
    assert len(clients["primary-secret"].models.calls) == 1


def test_bad_request_and_safety_do_not_call_secondary():
    for error in (ApiError(400, "INVALID_ARGUMENT"), ApiError(500, "safety blocked_reason")):
        pool, clients = make_pool([error], ["unused"])
        with pytest.raises(GeminiGenerationError) as caught:
            generate(pool)
        assert not caught.value.retryable
        assert len(clients["secondary-secret"].models.calls) == 0


def test_both_providers_exhausted_is_retryable():
    pool, _ = make_pool([ApiError(429), ApiError(429)], [ApiError(503), ApiError(503)])
    with pytest.raises(GeminiGenerationError) as caught:
        generate(pool)
    assert caught.value.retryable
    assert len(caught.value.attempts) == 4


def test_model_fallback_same_provider_before_secondary():
    pool, clients = make_pool([ApiError(404, "model not found"), "[]"], ["unused"])
    _, metadata = generate(pool)
    assert metadata["provider"] == "primary"
    assert metadata["model"] == "gemini-2.5-flash"
    assert [call["model"] for call in clients["primary-secret"].models.calls] == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]


def test_cooling_provider_is_skipped_on_next_generation():
    pool, clients = make_pool([ApiError(429), ApiError(429)], ["[]", "[]"])
    assert generate(pool)[1]["provider"] == "secondary"
    assert generate(pool)[1]["provider"] == "secondary"
    assert len(clients["primary-secret"].models.calls) == 2


@pytest.mark.parametrize(
    ("error", "category"),
    [(ApiError(429), TRANSIENT), (ApiError(401, "invalid key"), KEY_FAILURE), (ApiError(400), NON_RETRYABLE), (ApiError(404), MODEL_UNAVAILABLE), (Exception("safety blocked"), SAFETY_BLOCK)],
)
def test_error_classification(error, category):
    assert GeminiProviderPool.classify_error(error) == category


def test_logs_never_contain_keys(caplog):
    pool, _ = make_pool([ApiError(429), ApiError(429)], ["[]"])
    generate(pool)
    assert "primary-secret" not in caplog.text
    assert "secondary-secret" not in caplog.text
