"""Primary-secondary Gemini failover with safe error classification."""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol, cast

from google import genai
from google.genai import types

from config import settings
from errors import QuizGenerationError

LOG = logging.getLogger("services.gemini_pool")

TRANSIENT = "transient"
KEY_FAILURE = "key_failure"
NON_RETRYABLE = "non_retryable_request"
MODEL_UNAVAILABLE = "model_unavailable"
SAFETY_BLOCK = "safety_block"


class _ModelsClient(Protocol):
    def generate_content(self, **kwargs: Any) -> Any: ...


class _GeminiClient(Protocol):
    models: _ModelsClient


@dataclass(slots=True)
class Provider:
    label: str
    api_key: str
    state: str = "healthy"
    cooldown_until: datetime | None = None


class GeminiGenerationError(QuizGenerationError):
    def __init__(self, category: str, attempts: list[dict], *, retryable: bool):
        super().__init__(f"Gemini generation failed safely: {category}")
        self.category = category
        self.attempts = attempts
        self.retryable = retryable


class GeminiProviderPool:
    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        client_factory: Callable[[str], _GeminiClient] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        jitter: Callable[[], float] = random.random,
    ) -> None:
        env = environ if environ is not None else os.environ
        primary = (env.get("GEMINI_API_KEY_PRIMARY") or "").strip()
        secondary = (env.get("GEMINI_API_KEY_SECONDARY") or "").strip()
        legacy = (env.get("GEMINI_API_KEY") or "").strip()
        self.providers: list[Provider] = []
        if primary or secondary:
            if primary:
                self.providers.append(Provider("primary", primary))
            if secondary:
                self.providers.append(Provider("secondary", secondary))
        elif legacy:
            self.providers.append(Provider("primary", legacy))
        self.failover_enabled = _bool(env.get("GEMINI_FAILOVER_ENABLED"), settings.GEMINI_FAILOVER_ENABLED)
        self.max_attempts = max(1, int(env.get("GEMINI_MAX_ATTEMPTS_PER_KEY", settings.GEMINI_MAX_ATTEMPTS_PER_KEY)))
        self.timeout_seconds = max(1, int(env.get("GEMINI_REQUEST_TIMEOUT_SECONDS", settings.GEMINI_REQUEST_TIMEOUT_SECONDS)))
        self.cooldown_seconds = max(0, int(env.get("GEMINI_KEY_COOLDOWN_SECONDS", settings.GEMINI_KEY_COOLDOWN_SECONDS)))
        self.backoff_base = max(0.0, float(env.get("GEMINI_BACKOFF_BASE_SECONDS", settings.GEMINI_BACKOFF_BASE_SECONDS)))
        self.max_backoff = max(self.backoff_base, float(env.get("GEMINI_MAX_BACKOFF_SECONDS", settings.GEMINI_MAX_BACKOFF_SECONDS)))
        self.primary_model = (env.get("GEMINI_MODEL_PRIMARY") or settings.GEMINI_MODEL_PRIMARY).strip()
        self.fallback_model = (env.get("GEMINI_MODEL_FALLBACK") or settings.GEMINI_MODEL_FALLBACK).strip()
        self._client_factory = client_factory or self._default_client
        self._sleep = sleep
        self._now = now
        self._jitter = jitter

    def get_available_providers(self) -> list[Provider]:
        now = self._now()
        result = []
        for provider in self.providers:
            if provider.state == "cooling_down" and provider.cooldown_until and now >= provider.cooldown_until:
                provider.state = "healthy"
                provider.cooldown_until = None
            if provider.state == "healthy":
                result.append(provider)
        if not self.failover_enabled:
            return result[:1]
        return result

    def generate_subject_quiz(self, *, prompt: str, response_schema: dict) -> tuple[str, dict]:
        if not self.providers:
            raise GeminiGenerationError("not_configured", [], retryable=False)
        attempts: list[dict] = []
        providers = self.get_available_providers()
        if not providers:
            raise GeminiGenerationError("providers_cooling_down", [], retryable=True)

        for provider in providers:
            model = self.primary_model
            attempt_number = 0
            model_fallback_used = False
            while attempt_number < self.max_attempts:
                attempt_number += 1
                try:
                    response = self._call(provider, model, prompt, response_schema)
                    attempts.append({"provider": provider.label, "model": model, "category": "success"})
                    return response, {
                        "provider": provider.label,
                        "model": model,
                        "attempts": len(attempts),
                        "providers_attempted": list(dict.fromkeys(row["provider"] for row in attempts)),
                    }
                except Exception as exc:  # SDK exception types differ by release
                    category = self.classify_error(exc)
                    status = _safe_status(exc)
                    attempts.append({"provider": provider.label, "model": model, "category": category, "status": status})
                    LOG.warning(
                        "GEMINI_PROVIDER_FAILURE provider=%s model=%s error_category=%s status=%s",
                        provider.label, model, category, status or "unknown",
                    )
                    if category == MODEL_UNAVAILABLE and not model_fallback_used and self.fallback_model != model:
                        model = self.fallback_model
                        model_fallback_used = True
                        attempt_number -= 1
                        continue
                    if category in (NON_RETRYABLE, SAFETY_BLOCK):
                        raise GeminiGenerationError(category, attempts, retryable=False) from None
                    if category == KEY_FAILURE:
                        provider.state = "invalid"
                        break
                    if category == MODEL_UNAVAILABLE:
                        break
                    if category == TRANSIENT and attempt_number < self.max_attempts:
                        self._sleep(self.retry_with_backoff(attempt_number, exc))
                        continue
                    if category == TRANSIENT:
                        self.mark_provider_unhealthy(provider)
                    break

            next_provider = self.choose_next_provider(provider, providers)
            if next_provider:
                LOG.warning(
                    "GEMINI_PROVIDER_FAILOVER failed_provider=%s error_category=%s next_provider=%s",
                    provider.label, attempts[-1]["category"], next_provider.label,
                )

        final_category = attempts[-1]["category"] if attempts else "providers_unavailable"
        retryable = final_category in (TRANSIENT, MODEL_UNAVAILABLE)
        raise GeminiGenerationError(final_category, attempts, retryable=retryable)

    @staticmethod
    def classify_error(exc: Exception) -> str:
        status = _safe_status(exc)
        text = f"{type(exc).__name__} {exc}".lower()
        if status == 400 or any(token in text for token in ("invalid_argument", "malformed request", "invalid schema", "unsupported parameter")):
            return NON_RETRYABLE
        if any(token in text for token in ("safety", "blocked_reason", "prohibited content")):
            return SAFETY_BLOCK
        if status == 401 or any(token in text for token in ("invalid api key", "api key not valid", "revoked key", "authentication")):
            return KEY_FAILURE
        if status == 403 and any(token in text for token in ("key", "permission", "project")):
            return KEY_FAILURE
        if status == 404 or any(token in text for token in ("model not found", "model is not available", "unsupported model")):
            return MODEL_UNAVAILABLE
        if status in (408, 429, 500, 502, 503, 504) or any(token in text for token in (
            "resource_exhausted", "unavailable", "deadline_exceeded", "timeout", "timed out",
            "connection reset", "temporary failure", "temporarily unavailable", "dns",
        )):
            return TRANSIENT
        return NON_RETRYABLE

    def retry_with_backoff(self, attempt_number: int, exc: Exception | None = None) -> float:
        retry_after = _retry_after(exc)
        if retry_after is not None:
            return min(retry_after, self.max_backoff)
        base = min(self.backoff_base * (2 ** max(0, attempt_number - 1)), self.max_backoff)
        return min(base + self._jitter(), self.max_backoff)

    def mark_provider_unhealthy(self, provider: Provider) -> None:
        provider.state = "cooling_down"
        provider.cooldown_until = self._now() + timedelta(seconds=self.cooldown_seconds)

    @staticmethod
    def choose_next_provider(current: Provider, providers: list[Provider]) -> Provider | None:
        try:
            return providers[providers.index(current) + 1]
        except (ValueError, IndexError):
            return None

    def _call(self, provider: Provider, model: str, prompt: str, response_schema: dict) -> str:
        client = cast(_GeminiClient, self._client_factory(provider.api_key))
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=settings.GEMINI_FACTUAL_TEMPERATURE,
            ),
        )
        return response.text

    def _default_client(self, api_key: str):
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=self.timeout_seconds * 1000),
        )


def _safe_status(exc: Exception) -> int | None:
    for name in ("status_code", "code"):
        value = getattr(exc, name, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    response = getattr(exc, "response", None)
    try:
        value = getattr(response, "status_code", None)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _retry_after(exc: Exception | None) -> float | None:
    response = getattr(exc, "response", None) if exc else None
    headers = getattr(response, "headers", {}) or {}
    try:
        raw_value = headers.get("Retry-After")
        if raw_value is None:
            return None
        value = float(raw_value)
        return max(0.0, value)
    except (TypeError, ValueError):
        return None


def _bool(value: str | None, default: bool) -> bool:
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}
