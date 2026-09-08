from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.gemini_provider_pool import (
    KEY_FAILURE,
    MODEL_UNAVAILABLE,
    NON_RETRYABLE,
    SAFETY_BLOCK,
    TRANSIENT,
    GeminiGenerationError,
    GeminiProviderPool,
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
    return pool.generate_subject_quiz(prompt="safe prompt", response_schema={"type": "array"})


def test_primary_success_never_calls_secondary():
    pool, clients = make_pool(["[]"], ["unused"])
    text, metadata = generate(pool)
    assert text == "[]" and metadata["provider"] == "primary"
    assert len(clients["secondary-secret"].models.calls) == 0
    config = clients["primary-secret"].models.calls[0]["config"]
    assert config.temperature == 0.3
    assert config.response_json_schema == {"type": "array"}
    assert config.response_schema is None


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
    for errors in (
        [ApiError(400, "INVALID_ARGUMENT"), ApiError(400, "INVALID_ARGUMENT")],
        [ApiError(500, "safety blocked_reason")],
    ):
        pool, clients = make_pool(errors, ["unused"])
        with pytest.raises(GeminiGenerationError) as caught:
            generate(pool)
        assert not caught.value.retryable
        assert len(clients["secondary-secret"].models.calls) == 0


def test_bad_request_uses_configured_model_fallback_once():
    pool, clients = make_pool(
        [ApiError(400, "INVALID_ARGUMENT"), "[]"],
        ["unused"],
    )

    _, metadata = generate(pool)

    assert metadata["provider"] == "primary"
    assert metadata["model"] == "gemini-2.5-flash"
    assert [call["model"] for call in clients["primary-secret"].models.calls] == [
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
    ]


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
    assert [call["model"] for call in clients["primary-secret"].models.calls] == ["gemini-3.1-flash-lite", "gemini-2.5-flash"]


def test_cooling_provider_is_skipped_on_next_generation():
    pool, clients = make_pool([ApiError(429), ApiError(429)], ["[]", "[]"])
    assert generate(pool)[1]["provider"] == "secondary"
    assert generate(pool)[1]["provider"] == "secondary"
    assert len(clients["primary-secret"].models.calls) == 2


@pytest.mark.parametrize("error", [ApiError(503), ApiError(504), ApiError(404), TimeoutError("timeout")])
def test_repair_can_use_explicit_previously_successful_model_within_existing_budget(error):
    pool, clients = make_pool([error, "repaired batch"], ["unused"])
    text, metadata = pool.generate_subject_quiz(
        prompt="regenerate a complete batch", response_schema={"type": "array"},
        preferred_model="repair-model", alternate_model="successful-generator",
    )
    assert text == "repaired batch"
    assert metadata["model"] == "successful-generator"
    assert metadata["attempts"] == 2
    assert [call["model"] for call in clients["primary-secret"].models.calls] == [
        "repair-model", "successful-generator",
    ]
    assert clients["secondary-secret"].models.calls == []


def test_verifier_preferred_model_remains_pinned_without_explicit_alternate():
    pool, clients = make_pool([ApiError(504), ApiError(504)], ["verified"])
    _, metadata = pool.generate_subject_quiz(
        prompt="verify", response_schema={}, preferred_model="independent-verifier",
    )
    assert metadata["model"] == "independent-verifier"
    assert all(call["model"] == "independent-verifier" for client in clients.values() for call in client.models.calls)


def test_alternate_model_is_not_restarted_at_failed_repair_model_on_key_failover():
    pool, clients = make_pool([ApiError(504), ApiError(503)], ["repaired"])
    _, metadata = pool.generate_subject_quiz(
        prompt="repair", response_schema={}, preferred_model="repair-model",
        alternate_model="successful-generator",
    )
    assert metadata["provider"] == "secondary"
    assert metadata["model"] == "successful-generator"
    assert clients["secondary-secret"].models.calls[0]["model"] == "successful-generator"


def test_repair_alternate_does_not_bypass_quota_or_key_retry_policy():
    pool, clients = make_pool([ApiError(429), ApiError(429)], ["repaired"])
    _, metadata = pool.generate_subject_quiz(
        prompt="repair", response_schema={}, preferred_model="repair-model",
        alternate_model="successful-generator",
    )
    assert metadata["model"] == "repair-model"
    assert len(clients["primary-secret"].models.calls) == 2


def test_repair_alternate_does_not_add_an_attempt_when_budget_is_one():
    pool, clients = make_pool([ApiError(504)], [ApiError(504)], GEMINI_MAX_ATTEMPTS_PER_KEY="1")
    with pytest.raises(GeminiGenerationError) as caught:
        pool.generate_subject_quiz(
            prompt="repair", response_schema={}, preferred_model="repair-model",
            alternate_model="successful-generator",
        )
    assert caught.value.retryable
    assert len(caught.value.attempts) == 2
    assert all(len(client.models.calls) == 1 for client in clients.values())


@pytest.mark.parametrize("error", [ApiError(400), Exception("safety blocked")])
def test_repair_alternate_never_bypasses_request_or_safety_rejection(error):
    pool, clients = make_pool([error], ["unused"])
    with pytest.raises(GeminiGenerationError) as caught:
        pool.generate_subject_quiz(
            prompt="repair", response_schema={}, preferred_model="repair-model",
            alternate_model="successful-generator",
        )
    assert not caught.value.retryable
    assert len(clients["primary-secret"].models.calls) == 1
    assert clients["secondary-secret"].models.calls == []


def test_failed_repair_and_alternate_preserve_total_attempt_budget():
    pool, clients = make_pool([ApiError(504), ApiError(504)], [ApiError(504), ApiError(504)])
    with pytest.raises(GeminiGenerationError) as caught:
        pool.generate_subject_quiz(
            prompt="repair", response_schema={}, preferred_model="repair-model",
            alternate_model="successful-generator",
        )
    assert caught.value.retryable
    assert len(caught.value.attempts) == 4
    assert [call["model"] for client in clients.values() for call in client.models.calls] == [
        "repair-model", "successful-generator", "successful-generator", "successful-generator",
    ]


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


def test_provider_error_detail_preserves_reason_but_redacts_sensitive_values(caplog):
    credential = "AI" + "za" + "SyExampleCredentialValue" + "123456789"
    error = ApiError(
        400,
        f"INVALID_ARGUMENT schema has too many states; api_key={credential} "
        "https://example.test/request?key=also-secret",
    )
    pool, _ = make_pool([error], ["unused"])

    with pytest.raises(GeminiGenerationError):
        generate(pool)

    assert "schema has too many states" in caplog.text
    assert credential not in caplog.text
    assert "also-secret" not in caplog.text
