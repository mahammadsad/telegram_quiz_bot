"""Shared fail-closed validation for the versioned platform database contract."""

from __future__ import annotations

from collections.abc import Mapping

from database.contract import (
    PLATFORM_CONTRACT_KEY,
    PLATFORM_CONTRACT_MIGRATION_VERSION,
    PLATFORM_CONTRACT_REQUIRED_CHECKS,
    PLATFORM_CONTRACT_VERSION,
)


def failure_reasons(contract: Mapping[str, object]) -> tuple[str, ...]:
    """Return deterministic reasons why a platform contract is unsafe to use."""
    reasons: list[str] = []
    if contract.get("ready") is not True:
        reasons.append("not_ready")
    if contract.get("contract_key") != PLATFORM_CONTRACT_KEY:
        reasons.append("contract_key")
    if contract.get("contract_version") != PLATFORM_CONTRACT_VERSION:
        reasons.append("contract_version")
    if contract.get("required_migration_version") != PLATFORM_CONTRACT_MIGRATION_VERSION:
        reasons.append("migration_version")
    if contract.get("migration_applied") is not True:
        reasons.append("migration_ledger")

    checks = contract.get("checks")
    if not isinstance(checks, Mapping):
        reasons.append("checks")
        return tuple(dict.fromkeys(reasons))

    for name in PLATFORM_CONTRACT_REQUIRED_CHECKS:
        if checks.get(name) is not True:
            reasons.append(name)
    return tuple(dict.fromkeys(reasons))


def is_ready(contract: Mapping[str, object]) -> bool:
    return not failure_reasons(contract)
