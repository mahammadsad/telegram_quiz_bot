"""Read-only recovery preflight; never download or restore learner data."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verified_recovery_point import verify_recovery_point  # noqa: E402

PRODUCTION_REF = "tizxodkcpglmxgtwepor"
MAX_BACKUP_AGE = timedelta(hours=48)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def has_recent_completed_backup(payload: object, now: datetime) -> bool:
    """A configured backup/PITR toggle alone is not evidence of a backup."""
    if not isinstance(payload, dict) or not isinstance(payload.get("backups"), list):
        return False
    for backup in payload["backups"]:
        if not isinstance(backup, dict) or backup.get("status") != "COMPLETED":
            continue
        timestamp = backup.get("inserted_at")
        if not isinstance(timestamp, str):
            continue
        try:
            created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is not None and timedelta(0) <= now - created <= MAX_BACKUP_AGE:
            return True
    return False


def has_recent_pitr_window(payload: object, now: datetime) -> bool:
    """Require a real ordered recovery range, not merely enabled PITR settings."""
    if not isinstance(payload, dict):
        return False
    if payload.get("pitr_enabled") is not True or payload.get("walg_enabled") is not True:
        return False
    window = payload.get("physical_backup_data")
    if not isinstance(window, dict):
        return False
    earliest = window.get("earliest_physical_backup_date_unix")
    latest = window.get("latest_physical_backup_date_unix")
    # bool is an int subclass; API timestamps must be actual integer seconds.
    if type(earliest) is not int or type(latest) is not int:
        return False
    return (
        0 < earliest <= latest <= now.timestamp()
        and now.timestamp() - latest <= MAX_BACKUP_AGE.total_seconds()
    )


def backup_summary(payload: object, now: datetime) -> dict[str, bool | int | None]:
    """Allowlisted diagnostics only: no raw records, identifiers or URLs."""
    records = payload.get("backups") if isinstance(payload, dict) else None
    return {
        "backup_records": len(records) if isinstance(records, list) else None,
        "recent_completed_backup": has_recent_completed_backup(payload, now),
        "pitr_enabled": isinstance(payload, dict) and payload.get("pitr_enabled") is True,
        "recent_pitr_window": has_recent_pitr_window(payload, now),
    }


def application_recovery_gate(now: datetime) -> int:
    """No generic override: protected owner approval AND live provenance required."""
    try:
        raw = os.environ.get("APP_RECOVERY_EVIDENCE", "")
        if not raw:
            raise ValueError("Missing approval")
        plan_path = Path(os.environ["RUNNER_TEMP"]) / "production-migration-plan.txt"
        if plan_path.is_symlink() or plan_path.stat().st_size > 1024 * 1024:
            raise ValueError("Invalid plan")
        verify_recovery_point(
            raw,
            os.environ.get("GH_TOKEN", ""), now,
            plan=plan_path.read_text(encoding="utf-8"),
        )
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        print("No valid scoped application recovery approval; production migration blocked.")
        return 1
    print("Fresh owner-verified application recovery point confirmed for the exact reviewed migration only.")
    return 0


def main() -> int:
    if os.environ.get("EXPECTED_SUPABASE_PROJECT_REF") != PRODUCTION_REF:
        print("Backup preflight refused: production identity mismatch.")
        return 1
    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
    if not token:
        print("Backup preflight refused: management credential unavailable.")
        return 1
    request = Request(
        f"https://api.supabase.com/v1/projects/{PRODUCTION_REF}/database/backups",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with build_opener(NoRedirects()).open(request, timeout=20) as response:
            payload = json.loads(response.read(1024 * 1024 + 1))
    except (HTTPError, URLError, TimeoutError, ValueError):
        # Never echo provider bodies, credentials, backup IDs or download URLs.
        print("Provider backup preflight unavailable; checking scoped recovery evidence.")
        return application_recovery_gate(datetime.now(timezone.utc))
    summary = backup_summary(payload, datetime.now(timezone.utc))
    print("Backup evidence: " + json.dumps(summary, sort_keys=True))
    if not (summary["recent_completed_backup"] or summary["recent_pitr_window"]):
        print("No verified provider recovery point within 48 hours; checking scoped recovery evidence.")
        return application_recovery_gate(datetime.now(timezone.utc))
    print("Recent provider recovery point confirmed; restore drill is a separate gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
