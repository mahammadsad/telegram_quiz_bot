"""Print a sanitized verified-inventory capacity report for operators."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Callable, TypeVar

import httpx

from config.settings import (
    QUIZ_DIFFICULTY_DISTRIBUTION,
    require_env,
    supabase_project_ref_matches,
)
from config.subjects import QUIZ_SUBJECTS
from config.syllabus import CHAPTERS
from services.question_inventory import (
    chapter_difficulty_report,
    exposure_quality_report,
    inventory_report,
    replenishment_plan,
    replenishment_quality_report,
)
from storage import content_inventory_repo

_T = TypeVar("_T")
_READ_ATTEMPTS = 3
_REPLENISHMENT_EVENT_DAYS = 7
_REPLENISHMENT_EVENT_LIMIT = 1000


def _read_with_retry(operation: Callable[[], _T]) -> _T:
    """Retry only transient read transport failures; never mask database errors."""
    for attempt in range(_READ_ATTEMPTS):
        try:
            return operation()
        except httpx.TransportError:
            if attempt == _READ_ATTEMPTS - 1:
                raise
            time.sleep(0.5 * (2**attempt))
    raise AssertionError("unreachable")


def main() -> int:
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    require_env("EXPECTED_SUPABASE_PROJECT_REF")
    if not supabase_project_ref_matches():
        raise RuntimeError("Supabase project ownership check failed.")
    now = datetime.now(timezone.utc)
    report = {}
    for subject in QUIZ_SUBJECTS:
        subject_key = subject.key
        rows = _read_with_retry(
            partial(
                content_inventory_repo.list_verified_candidates,
                subject_key,
                now=now,
                limit=1000,
            )
        )
        capacity = inventory_report(rows, now=now).get(
            subject_key,
            {
                "verified": 0,
                "eligible_now": 0,
                "verified_days": 0.0,
                "eligible_days": 0.0,
            },
        )
        recent_usage = _read_with_retry(
            partial(
                content_inventory_repo.list_recent_usage,
                subject_key,
                since=now - timedelta(days=30),
            )
        )
        report[subject_key] = {
            **capacity,
            "chapter_difficulty": chapter_difficulty_report(
                rows,
                CHAPTERS[subject_key],
                QUIZ_DIFFICULTY_DISTRIBUTION,
                now=now,
            ),
            "replenishment": replenishment_plan(int(capacity["verified"])),
            "exposure_quality_30d": exposure_quality_report(recent_usage),
        }
    replenishment_events = _read_with_retry(
        partial(
            content_inventory_repo.list_recent_replenishment_events,
            since=now - timedelta(days=_REPLENISHMENT_EVENT_DAYS),
            limit=_REPLENISHMENT_EVENT_LIMIT,
        )
    )
    print(json.dumps({
        "generated_at": now.isoformat(),
        "subjects": report,
        "replenishment_quality_7d": replenishment_quality_report(
            replenishment_events,
            sample_limit=_REPLENISHMENT_EVENT_LIMIT,
        ),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
