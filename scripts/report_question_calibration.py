"""Print bounded, aggregate-only question diagnostics for operators."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from config.settings import require_env, supabase_project_ref_matches
from services.question_calibration import calibration_report
from storage.question_calibration_repo import list_first_attempt_observations


def main() -> int:
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    require_env("EXPECTED_SUPABASE_PROJECT_REF")
    if not supabase_project_ref_matches():
        raise RuntimeError("Supabase project ownership check failed.")
    now = datetime.now(timezone.utc)
    observations = list_first_attempt_observations(since=now - timedelta(days=90))
    report = calibration_report(observations)
    print(json.dumps({"generated_at": now.isoformat(), "window_days": 90, **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
