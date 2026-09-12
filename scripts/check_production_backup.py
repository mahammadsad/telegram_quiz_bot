"""Read-only provider backup preflight; never download or restore learner data."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

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
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        # Never echo provider bodies, credentials, backup IDs or download URLs.
        print("Backup preflight unavailable; production migration remains blocked.")
        return 1
    if not has_recent_completed_backup(payload, datetime.now(timezone.utc)):
        print("No completed provider backup within 48 hours; production migration blocked.")
        return 1
    print("Recent completed provider backup confirmed; restore drill is a separate gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
