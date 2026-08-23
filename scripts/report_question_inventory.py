"""Print a sanitized verified-inventory capacity report for operators."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from config.settings import require_env, supabase_project_ref_matches
from config.subjects import QUIZ_SUBJECTS
from services.question_inventory import (
    exposure_quality_report,
    inventory_report,
    replenishment_plan,
)
from storage import content_inventory_repo


def main() -> int:
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    require_env("EXPECTED_SUPABASE_PROJECT_REF")
    if not supabase_project_ref_matches():
        raise RuntimeError("Supabase project ownership check failed.")
    now = datetime.now(timezone.utc)
    report = {}
    for subject in QUIZ_SUBJECTS:
        rows = content_inventory_repo.list_verified_candidates(
            subject.key,
            now=now,
            limit=1000,
        )
        capacity = inventory_report(rows, now=now).get(
            subject.key,
            {
                "verified": 0,
                "eligible_now": 0,
                "verified_days": 0.0,
                "eligible_days": 0.0,
            },
        )
        recent_usage = content_inventory_repo.list_recent_usage(
            subject.key,
            since=now - timedelta(days=30),
        )
        report[subject.key] = {
            **capacity,
            "replenishment": replenishment_plan(int(capacity["verified"])),
            "exposure_quality_30d": exposure_quality_report(recent_usage),
        }
    print(json.dumps({"generated_at": now.isoformat(), "subjects": report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
