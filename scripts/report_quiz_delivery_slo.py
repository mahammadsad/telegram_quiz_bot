"""Print privacy-safe delivery SLOs from durable production quiz jobs."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from config.settings import require_env, supabase_project_ref_matches
from services.quiz_delivery_slo import quiz_delivery_slo_report
from storage import quiz_jobs_repo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--fail-on-terminal",
        action="store_true",
        help="Exit non-zero when the window contains terminal delivery failures.",
    )
    args = parser.parse_args()
    if args.days not in range(1, 32):
        raise SystemExit("--days must be between 1 and 31")
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    require_env("EXPECTED_SUPABASE_PROJECT_REF")
    if not supabase_project_ref_matches():
        raise RuntimeError("Supabase project ownership check failed.")
    start_date = args.end_date - timedelta(days=args.days - 1)
    rows = quiz_jobs_repo.list_delivery_slo_window(
        start_date.isoformat(), args.end_date.isoformat()
    )
    report = quiz_delivery_slo_report(
        rows,
        start_date=start_date,
        end_date=args.end_date,
    )
    print(json.dumps(report, sort_keys=True))
    return int(bool(args.fail_on_terminal and report["summary"]["terminalFailureJobs"]))


if __name__ == "__main__":
    raise SystemExit(main())
