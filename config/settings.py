"""
Central configuration.

Every environment variable and tunable constant used anywhere in the
project is declared here so there is exactly one place to look when
deploying, testing locally, or tuning behavior. Nothing outside this
module should call os.environ.get() directly for a setting.
"""

from __future__ import annotations

import logging
import os
import sys

LOG = logging.getLogger("config")


def require_env(name: str) -> str:
    """Fetch a required env var or exit(1) with a clear error.

    Used for secrets that truly cannot have a default (API keys, tokens).
    """
    value = os.environ.get(name)
    if not value:
        LOG.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return value


# --------------------------------------------------------------------------
# Supabase (database)
# --------------------------------------------------------------------------
# Use the service_role key, not the anon key — this project runs entirely
# server-side (GitHub Actions), never in a browser, and needs write access
# that bypasses row-level security policies you may add later for the
# public website/app.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
# Mini App direct-link identity. The public username/short name are used to
# build https://t.me/<bot>/<shortname>?startapp=<quiz_id> links.
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
MINIAPP_SHORT_NAME = os.environ.get("MINIAPP_SHORT_NAME", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# The API validates Telegram Mini App initData before accepting answers.
# Set DEV_ALLOW_UNVERIFIED_TELEGRAM=true only for local browser testing.
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS = int(os.environ.get("TELEGRAM_INIT_DATA_MAX_AGE_SECONDS", "86400"))
DEV_ALLOW_UNVERIFIED_TELEGRAM = os.environ.get("DEV_ALLOW_UNVERIFIED_TELEGRAM", "false").strip().lower() == "true"

# Comma-separated list for deployments that serve index.html from a different
# origin than the API. Empty means same-origin only.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# All daily quiz IDs are based on the audience timezone, not the server's
# default timezone. GitHub Actions and many Python hosts run in UTC.
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"

# --------------------------------------------------------------------------
# Bot identity. repo_1 uses "daily_mcq"; this repo writes quiz packs as the
# second shared bot type already present in database/schema.sql.
# --------------------------------------------------------------------------
BOT_TYPE = "mock_test"
SESSION_TYPE = "mock_test"

# --------------------------------------------------------------------------
# Quiz-pack generation behavior
# --------------------------------------------------------------------------
QUESTIONS_PER_RUN = int(os.environ.get("QUESTIONS_PER_RUN", "10"))
CURRENT_AFFAIRS_MIN = 2
CURRENT_AFFAIRS_MAX = 3
GEOGRAPHY_MIN = 1
GEOGRAPHY_MAX = 2

DUPLICATE_LOOKBACK_DAYS = 14     # "don't repeat these" window fed to Gemini
SPACED_REPETITION_OFFSETS = (3, 7, 14)

EXAM_TARGETS = "WBCS, WBP Constable/SI, Kolkata Police, PSC Clerkship, WB Miscellaneous, Primary TET"

# Telegram's own limits are ~300 / 100 / 200 chars, but we deliberately slice
# tighter as a safety margin.
TELEGRAM_QUESTION_LIMIT = 250
TELEGRAM_OPTION_LIMIT = 100
TELEGRAM_EXPLANATION_LIMIT = 199
TELEGRAM_DETAILED_EXPLANATION_LIMIT = 900

# --------------------------------------------------------------------------
# Global Question Scheduler tuning (System 1 — see scheduler/question_scheduler.py)
# --------------------------------------------------------------------------
# Minimum days before a used question becomes eligible for reuse. The actual
# gap grows with usage_count (see scheduler), this is just the base unit.
SCHEDULER_MIN_REUSE_GAP_DAYS = int(os.environ.get("SCHEDULER_MIN_REUSE_GAP_DAYS", "21"))
SCHEDULER_MAX_REUSE_GAP_DAYS = int(os.environ.get("SCHEDULER_MAX_REUSE_GAP_DAYS", "180"))

# How many candidate rows to pull from the DB per subject when scoring the
# eligible pool (keeps the query cheap regardless of how large the bank gets).
SCHEDULER_POOL_FETCH_LIMIT = 50

# Near-duplicate cutoff for pg_trgm similarity() in [0, 1]. Below this, two
# questions are considered unrelated; at/above it, the newer one is treated
# as a duplicate of the existing row instead of being inserted.
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.82"))

# --------------------------------------------------------------------------
# repo_2 operational state keys. Syllabus memory now lives in bot_state
# instead of syllabus_state.json so no generated state needs committing.
# --------------------------------------------------------------------------
SYLLABUS_STATE_KEY = "mock_test_syllabus_state"
QUIZ_PACK_SOURCE_PREFIX = "quiz_pack:"
