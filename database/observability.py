"""Request-local, payload-free database operation timings."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

DatabaseTiming = tuple[str, float]

_DATABASE_TIMINGS: ContextVar[list[DatabaseTiming] | None] = ContextVar(
    "database_timings",
    default=None,
)
_SAFE_LABEL = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


def begin_database_timings() -> tuple[list[DatabaseTiming], Token[list[DatabaseTiming] | None]]:
    timings: list[DatabaseTiming] = []
    return timings, _DATABASE_TIMINGS.set(timings)


def reset_database_timings(token: Token[list[DatabaseTiming] | None]) -> None:
    _DATABASE_TIMINGS.reset(token)


@contextmanager
def database_timing(label: str) -> Iterator[None]:
    """Record one fixed operation label and duration, never its arguments."""
    safe_label = label if _SAFE_LABEL.fullmatch(label) else "database.operation"
    started_at = time.perf_counter()
    try:
        yield
    finally:
        timings = _DATABASE_TIMINGS.get()
        if timings is not None and len(timings) < 32:
            timings.append((safe_label, max(0.0, (time.perf_counter() - started_at) * 1000)))
