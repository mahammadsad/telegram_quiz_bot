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

from errors import ConfigurationError

LOG = logging.getLogger("config")


def require_env(name: str) -> str:
    """Fetch a required environment value without terminating the process."""
    value = os.environ.get(name)
    if not value:
        LOG.error("Missing required environment variable: %s", name)
        raise ConfigurationError(f"Missing required environment variable: {name}")
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
# API keys are intentionally resolved inside services/gemini_provider_pool.py.
# Keeping them out of module-level constants makes it much harder for an
# accidental settings dump/repr to disclose a credential and lets tests inject
# a private environment mapping without mutating global state.
GEMINI_MODEL_PRIMARY = os.environ.get(
    "GEMINI_MODEL_PRIMARY",
    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
).strip() or "gemini-2.5-flash-lite"
GEMINI_MODEL_FALLBACK = os.environ.get(
    "GEMINI_MODEL_FALLBACK", "gemini-2.5-flash"
).strip() or "gemini-2.5-flash"

# Backward-compatible alias for older modules/database provenance. New
# generation code always uses the explicit primary/fallback names above.
GEMINI_MODEL = GEMINI_MODEL_PRIMARY

GEMINI_FAILOVER_ENABLED = os.environ.get(
    "GEMINI_FAILOVER_ENABLED", "true"
).strip().lower() == "true"
GEMINI_MAX_ATTEMPTS_PER_KEY = max(
    1, int(os.environ.get("GEMINI_MAX_ATTEMPTS_PER_KEY", "2"))
)
GEMINI_REQUEST_TIMEOUT_SECONDS = max(
    1, int(os.environ.get("GEMINI_REQUEST_TIMEOUT_SECONDS", "120"))
)
GEMINI_KEY_COOLDOWN_SECONDS = max(
    0, int(os.environ.get("GEMINI_KEY_COOLDOWN_SECONDS", "900"))
)
GEMINI_BACKOFF_BASE_SECONDS = max(
    0.0, float(os.environ.get("GEMINI_BACKOFF_BASE_SECONDS", "2"))
)
GEMINI_MAX_BACKOFF_SECONDS = max(
    GEMINI_BACKOFF_BASE_SECONDS,
    float(os.environ.get("GEMINI_MAX_BACKOFF_SECONDS", "60")),
)
GEMINI_FACTUAL_TEMPERATURE = min(
    0.4,
    max(0.0, float(os.environ.get("GEMINI_FACTUAL_TEMPERATURE", "0.3"))),
)

# Every newly generated pack is grounded in operator-verified source facts and
# then checked by a separate source-only Gemini request. Current-affairs facts
# expire quickly even when a source row has a later explicit expiry.
QUESTION_VERIFICATION_MIN_CONFIDENCE = min(
    1.0,
    max(0.5, float(os.environ.get("QUESTION_VERIFICATION_MIN_CONFIDENCE", "0.85"))),
)
CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS = max(
    1, min(45, int(os.environ.get("CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS", "45")))
)
QUESTION_REPORT_THRESHOLD = max(
    2, int(os.environ.get("QUESTION_REPORT_THRESHOLD", "3"))
)

# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
# Mini App direct-link identity. The public username/short name are used to
# build https://t.me/<bot>/<shortname>?startapp=<quiz_id> links.
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
MINIAPP_SHORT_NAME = os.environ.get("MINIAPP_SHORT_NAME", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_FORUM_TOPICS_JSON = os.environ.get("TELEGRAM_FORUM_TOPICS_JSON", "").strip()
# Telegram's General forum topic sometimes expects no message_thread_id. Set
# this only after discovering a real numeric ID; an empty value deliberately
# means announcements are sent without message_thread_id.
TELEGRAM_GENERAL_THREAD_ID = os.environ.get("TELEGRAM_GENERAL_THREAD_ID", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "").strip()
TELEGRAM_ADMIN_USER_IDS = os.environ.get("TELEGRAM_ADMIN_USER_IDS", "").strip()

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

# Static hosting fallback. When true, bot.py also writes quizzes/<quiz_id>.json
# after storing the generated pack in Supabase, so GitHub Pages can still show
# the quiz even when the FastAPI Mini App URL is not wired yet.
WRITE_STATIC_QUIZ_JSON = os.environ.get("WRITE_STATIC_QUIZ_JSON", "true").strip().lower() == "true"

# --------------------------------------------------------------------------
# Bot identity. repo_1 uses "daily_mcq"; this repo writes quiz packs as the
# second shared bot type already present in database/schema.sql.
# --------------------------------------------------------------------------
BOT_TYPE = "mock_test"
SESSION_TYPE = "mock_test"

# --------------------------------------------------------------------------
# Quiz-pack generation behavior
# --------------------------------------------------------------------------
QUESTIONS_PER_RUN = 10
QUIZ_DIFFICULTY_DISTRIBUTION = {"easy": 3, "medium": 5, "hard": 2}
QUIZ_CLAIM_TIMEOUT_MINUTES = max(
    5, int(os.environ.get("QUIZ_CLAIM_TIMEOUT_MINUTES", "20"))
)
CURRENT_AFFAIRS_MIN = 2
CURRENT_AFFAIRS_MAX = 3
GEOGRAPHY_MIN = 1
GEOGRAPHY_MAX = 2

DUPLICATE_LOOKBACK_DAYS = 14     # "don't repeat these" window fed to Gemini
SPACED_REPETITION_OFFSETS = (3, 7, 14, 30)

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
