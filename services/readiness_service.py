"""Fail-closed, sanitized readiness assessment for Render and operators."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from config.settings import (
    EXPECTED_SUPABASE_PROJECT_REF,
    GEMINI_FAILOVER_ENABLED,
    MINIAPP_SHORT_NAME,
    QUESTION_VERIFICATION_MIN_CONFIDENCE,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_CHAT_ID,
    TELEGRAM_FORUM_TOPICS_JSON,
    TELEGRAM_GENERAL_THREAD_ID,
    gemini_provider_configuration,
    supabase_project_ref_matches,
)
from database.contract import (
    APPLICATION_VERSION,
    DATABASE_CONTRACT_KEY,
    DATABASE_CONTRACT_VERSION,
    REQUIRED_MIGRATION_VERSION,
)
from storage import schema_contract_repo
from telegram.routing import ForumRouter, ForumRoutingError

LOG = logging.getLogger("services.readiness")
_CACHE: tuple[float, "Readiness"] | None = None


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    checks: dict[str, bool]
    categories: tuple[str, ...]
    provider_category: str

    def public_payload(self) -> dict:
        return {
            "ok": self.ready,
            "status": "ready" if self.ready else "not_ready",
            "checks": self.checks,
            "failureCategories": list(self.categories),
            "aiProviderCategory": self.provider_category,
            "applicationVersion": APPLICATION_VERSION,
            "requiredMigrationVersion": REQUIRED_MIGRATION_VERSION,
            "databaseContractVersion": DATABASE_CONTRACT_VERSION,
        }


def assess(*, use_cache: bool = True) -> Readiness:
    global _CACHE
    now = time.monotonic()
    if use_cache and _CACHE and now - _CACHE[0] < 15:
        return _CACHE[1]

    checks = {
        "criticalEnvironment": False,
        "environmentOwnership": False,
        "telegramConfiguration": False,
        "aiConfiguration": False,
        "supabaseConnectivity": False,
        "databaseContract": False,
        "databasePermissions": False,
        "activeQuizRetrieval": False,
    }
    failures: list[str] = []

    primary, secondary = gemini_provider_configuration()
    provider_category = (
        "primary_and_secondary"
        if primary and secondary
        else "primary_only"
        if primary
        else "secondary_only"
        if secondary
        else "unavailable"
    )

    checks["criticalEnvironment"] = bool(
        SUPABASE_URL
        and SUPABASE_SERVICE_KEY
        and EXPECTED_SUPABASE_PROJECT_REF
        and TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
        and TELEGRAM_BOT_USERNAME
        and MINIAPP_SHORT_NAME
    )
    if not checks["criticalEnvironment"]:
        failures.append("configuration")

    checks["environmentOwnership"] = bool(
        EXPECTED_SUPABASE_PROJECT_REF and supabase_project_ref_matches()
    )
    if not checks["environmentOwnership"]:
        failures.append("environment_ownership")

    try:
        ForumRouter.from_values(TELEGRAM_FORUM_TOPICS_JSON, TELEGRAM_GENERAL_THREAD_ID)
        checks["telegramConfiguration"] = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    except ForumRoutingError:
        checks["telegramConfiguration"] = False
    if not checks["telegramConfiguration"]:
        failures.append("telegram_configuration")

    checks["aiConfiguration"] = primary or (secondary and GEMINI_FAILOVER_ENABLED)
    if not checks["aiConfiguration"]:
        failures.append("ai_configuration")

    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            contract = schema_contract_repo.get_contract()
            checks["supabaseConnectivity"] = True
            permission_failures = (
                contract.get("function_permission_failures") or []
            ) + (contract.get("table_permission_failures") or [])
            checks["databasePermissions"] = not permission_failures
            checks["databaseContract"] = bool(
                contract.get("ready")
                and contract.get("contract_key") == DATABASE_CONTRACT_KEY
                and contract.get("contract_version") == DATABASE_CONTRACT_VERSION
                and contract.get("required_migration_version")
                == REQUIRED_MIGRATION_VERSION
                and float(contract.get("verification_threshold") or 0)
                == QUESTION_VERIFICATION_MIN_CONFIDENCE
            )
            active = schema_contract_repo.active_quiz_probe()
            checks["activeQuizRetrieval"] = bool(
                active
                and active.get("question_count") == 10
                and active.get("integrity_verified")
                and int(active.get("checksum_contract_version") or 0) == 2
                and active.get("generated_checksum")
                == active.get("persisted_checksum")
            )
        except Exception as exc:
            LOG.warning(
                "READINESS_DATABASE_FAILURE category=%s",
                type(exc).__name__,
            )
    if not checks["supabaseConnectivity"]:
        failures.append("database_connectivity")
    elif not checks["databaseContract"]:
        failures.append("database_contract")
    if not checks["databasePermissions"]:
        failures.append("database_permissions")
    if not checks["activeQuizRetrieval"]:
        failures.append("active_quiz_retrieval")

    result = Readiness(
        ready=all(checks.values()),
        checks=checks,
        categories=tuple(dict.fromkeys(failures)),
        provider_category=provider_category,
    )
    _CACHE = (now, result)
    return result
