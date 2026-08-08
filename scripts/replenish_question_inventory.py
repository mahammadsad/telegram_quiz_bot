"""Claim and process durable verified-inventory replenishment jobs."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone

from bot import validate_database_schema
from config.settings import require_env, supabase_project_ref_matches
from services.content_replenishment_service import process_due_replenishment_jobs
from services.gemini_provider_pool import GeminiProviderPool


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    require_env("SUPABASE_URL")
    require_env("SUPABASE_SERVICE_KEY")
    require_env("EXPECTED_SUPABASE_PROJECT_REF")
    if not supabase_project_ref_matches():
        raise RuntimeError("Supabase project ownership check failed.")
    validate_database_schema()
    worker_id = (
        f"inventory:{os.environ.get('GITHUB_RUN_ID', 'local')}:"
        f"{uuid.uuid4().hex[:12]}"
    )
    result = process_due_replenishment_jobs(
        GeminiProviderPool(),
        worker_id=worker_id,
        now=datetime.now(timezone.utc),
        limit=max(1, min(args.limit, 25)),
    )
    print(json.dumps({
        "ensured": result.ensured,
        "claimed": result.claimed,
        "outcomes": result.outcomes,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
