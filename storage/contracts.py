"""Runtime-checked types at the Supabase/PostgREST boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

Row: TypeAlias = dict[str, Any]
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
SAFE_RATE_LIMIT_MESSAGES = (
    "bookmark rate limit exceeded",
    "practice answer rate limit exceeded",
    "preferences rate limit exceeded",
    "quiz submission rate limit exceeded",
    "report rate limit exceeded",
    "resource feedback rate limit exceeded",
    "resource review rate limit exceeded",
)


class StorageContractError(RuntimeError):
    """The database returned a shape that violates a repository contract."""


def raise_safe_rate_limit(exc: Exception) -> None:
    """Translate only known database limiter messages without leaking RPC details."""
    message = str(exc).casefold()
    for safe_message in SAFE_RATE_LIMIT_MESSAGES:
        if safe_message in message:
            raise ValueError(safe_message) from exc


def as_row(value: object, context: str) -> Row:
    if not isinstance(value, Mapping):
        raise StorageContractError(f"{context} returned a non-object row")
    if any(not isinstance(key, str) for key in value):
        raise StorageContractError(f"{context} returned a row with a non-string key")
    return dict(value)


def as_rows(value: object, context: str) -> list[Row]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StorageContractError(f"{context} returned a non-array result")
    return [as_row(item, context) for item in value]


def first_row(value: object, context: str) -> Row | None:
    rows = as_rows(value, context)
    return rows[0] if rows else None


def as_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise StorageContractError(f"{context} returned a non-numeric scalar")
    try:
        return int(value)
    except ValueError as exc:
        raise StorageContractError(f"{context} returned an invalid integer") from exc


def as_json_value(value: object, context: str) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise StorageContractError(f"{context} contains a non-string JSON key")
        return {
            str(key): as_json_value(item, context)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [as_json_value(item, context) for item in value]
    raise StorageContractError(f"{context} contains a non-JSON value")
