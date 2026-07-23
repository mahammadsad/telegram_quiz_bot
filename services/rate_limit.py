"""Small process-local abuse guard complementing database transaction limits.

Database RPCs remain the authoritative concurrency and submission protection.
This limiter reduces accidental button storms before they reach Supabase.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimitExceeded(ValueError):
    def __init__(self, retry_after_seconds: int):
        super().__init__("অনেকবার অনুরোধ করা হয়েছে। একটু পরে আবার চেষ্টা করুন।")
        self.retry_after_seconds = max(1, retry_after_seconds)


_EVENTS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def check(key: str, *, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        events = _EVENTS[key]
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            retry_after = int(window_seconds - (now - events[0])) + 1
            raise RateLimitExceeded(retry_after)
        events.append(now)


def reset_for_tests() -> None:
    with _LOCK:
        _EVENTS.clear()
