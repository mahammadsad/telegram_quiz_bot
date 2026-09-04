"""
Central configuration.

Every environment variable and tunable constant used anywhere in the
project is declared here so there is exactly one place to look when
deploying, testing locally, or tuning behavior. Nothing outside this
module should call os.environ.get() directly for a setting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from errors import ConfigurationError

LOG = logging.getLogger("config")

_PRODUCTION_CONFIG_PATH = Path(__file__).with_name("production.toml")
PRODUCTION_CONFIG = tomllib.loads(_PRODUCTION_CONFIG_PATH.read_text(encoding="utf-8"))
PRODUCTION_CONFIG_VERSION = str(PRODUCTION_CONFIG["meta"]["version"])
PRODUCTION_CONFIG_HASH = hashlib.sha256(
    json.dumps(PRODUCTION_CONFIG, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _locked_value(env_name: str, configured: object) -> str:
    """Reject deployment drift while retaining same-value legacy variables."""
    expected = str(configured).lower() if isinstance(configured, bool) else str(configured)
    actual = os.environ.get(env_name)
    if actual is not None and actual.strip().lower() != expected.lower():
        raise ConfigurationError(
            f"{env_name} conflicts with config/production.toml."
        )
    return expected


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
EXPECTED_SUPABASE_PROJECT_REF = os.environ.get(
    "EXPECTED_SUPABASE_PROJECT_REF", ""
).strip()


def supabase_project_ref_matches(
    url: str = SUPABASE_URL,
    expected_ref: str = EXPECTED_SUPABASE_PROJECT_REF,
) -> bool:
    """Fail safely when an environment points at the wrong hosted project."""
    if not expected_ref:
        return False
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if expected_ref.lower() == "local":
        return hostname in {"localhost", "127.0.0.1", "::1"}
    return hostname == f"{expected_ref.lower()}.supabase.co"

# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
# API keys are intentionally resolved inside services/gemini_provider_pool.py.
# Keeping them out of module-level constants makes it much harder for an
# accidental settings dump/repr to disclose a credential and lets tests inject
# a private environment mapping without mutating global state.
GEMINI_MODEL_PRIMARY = os.environ.get(
    "GEMINI_MODEL_PRIMARY",
    _locked_value("GEMINI_MODEL", PRODUCTION_CONFIG["gemini"]["primary_model"]),
).strip()
_locked_value("GEMINI_MODEL_PRIMARY", PRODUCTION_CONFIG["gemini"]["primary_model"])
GEMINI_MODEL_FALLBACK = os.environ.get(
    "GEMINI_MODEL_FALLBACK",
    _locked_value("GEMINI_MODEL_FALLBACK", PRODUCTION_CONFIG["gemini"]["fallback_model"]),
).strip()
GEMINI_VERIFIER_MODEL = os.environ.get(
    "GEMINI_VERIFIER_MODEL",
    _locked_value("GEMINI_VERIFIER_MODEL", PRODUCTION_CONFIG["gemini"]["verifier_model"]),
).strip()

# Backward-compatible alias for older modules/database provenance. New
# generation code always uses the explicit primary/fallback names above.
GEMINI_MODEL = GEMINI_MODEL_PRIMARY

GEMINI_FAILOVER_ENABLED = os.environ.get(
    "GEMINI_FAILOVER_ENABLED",
    _locked_value("GEMINI_FAILOVER_ENABLED", PRODUCTION_CONFIG["gemini"]["failover_enabled"]),
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
    max(0.5, float(_locked_value(
        "QUESTION_VERIFICATION_MIN_CONFIDENCE",
        PRODUCTION_CONFIG["quiz"]["verification_min_confidence"],
    ))),
)
CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS = max(
    1,
    min(45, int(_locked_value(
        "CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS",
        PRODUCTION_CONFIG["current_affairs"]["max_source_age_days"],
    ))),
)
SOURCE_BACKED_ROTATION_ENABLED = _locked_value(
    "SOURCE_BACKED_ROTATION_ENABLED",
    PRODUCTION_CONFIG["quiz"]["source_backed_rotation_enabled"],
).lower() == "true"
SOURCE_OPTIONAL_STABLE_SUBJECTS_ENABLED = _locked_value(
    "SOURCE_OPTIONAL_STABLE_SUBJECTS_ENABLED",
    PRODUCTION_CONFIG["quiz"]["source_optional_stable_subjects_enabled"],
).lower() == "true"
DETERMINISTIC_PROOF_VERSION = int(
    PRODUCTION_CONFIG["verification"]["deterministic_proof_version"]
)
DETERMINISTIC_PROOF_REQUIRED = bool(
    PRODUCTION_CONFIG["verification"]["require_new_candidate_proof"]
)
CONTENT_INVENTORY_TARGET_DAYS = int(PRODUCTION_CONFIG["content_inventory"]["target_days"])
CONTENT_INVENTORY_BATCH_SIZE = int(
    PRODUCTION_CONFIG["content_inventory"]["generation_batch_size"]
)
CONTENT_CHAPTER_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["chapter_cooldown_days"]
)
CONTENT_TOPIC_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["topic_cooldown_days"]
)
CONTENT_MICRO_TOPIC_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["micro_topic_cooldown_days"]
)
CONTENT_SOURCE_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["source_cooldown_days"]
)
CONTENT_KNOWLEDGE_POINT_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["knowledge_point_cooldown_days"]
)
CONTENT_EXACT_VARIANT_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["exact_variant_cooldown_days"]
)
CONTENT_SEMANTIC_NEAR_COOLDOWN_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["semantic_near_cooldown_days"]
)
CONTENT_QUIZ_OVERLAP_WINDOW_DAYS = int(
    PRODUCTION_CONFIG["content_inventory"]["quiz_overlap_window_days"]
)
CONTENT_MAX_QUIZ_OVERLAP_RATIO = float(
    PRODUCTION_CONFIG["content_inventory"]["max_quiz_overlap_ratio"]
)
QUESTION_REPORT_THRESHOLD = max(
    2,
    int(_locked_value(
        "QUESTION_REPORT_THRESHOLD",
        PRODUCTION_CONFIG["quiz"]["question_report_threshold"],
    )),
)

# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
# Mini App direct-link identity. The public username/short name are used to
# build https://t.me/<bot>/<shortname>?startapp=<quiz_id> links.
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
MINIAPP_SHORT_NAME = os.environ.get("MINIAPP_SHORT_NAME", "").strip()
PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "").strip().rstrip("/")
PUBLIC_API_BASE_URL = os.environ.get("PUBLIC_API_BASE_URL", PUBLIC_APP_URL).strip().rstrip("/")
CITIZEN_AFFAIRS_URL = os.environ.get(
    "CITIZEN_AFFAIRS_URL", PRODUCTION_CONFIG["brand"]["parent_site_url"]
).strip()
DATABASE_REQUEST_TIMEOUT_SECONDS = max(
    3,
    min(
        30,
        int(
            _locked_value(
                "DATABASE_REQUEST_TIMEOUT_SECONDS",
                PRODUCTION_CONFIG["database"]["request_timeout_seconds"],
            )
        ),
    ),
)
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
TELEGRAM_WRITE_INIT_DATA_MAX_AGE_SECONDS = min(
    TELEGRAM_INIT_DATA_MAX_AGE_SECONDS,
    max(60, int(os.environ.get("TELEGRAM_WRITE_INIT_DATA_MAX_AGE_SECONDS", "3600"))),
)
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
APP_TIMEZONE = _locked_value(
    "APP_TIMEZONE", PRODUCTION_CONFIG["scheduler"]["timezone"]
)

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
QUESTIONS_PER_RUN = int(PRODUCTION_CONFIG["quiz"]["question_count"])
QUIZ_DIFFICULTY_DISTRIBUTION = {"easy": 3, "medium": 5, "hard": 2}
QUIZ_CORRECT_MARKS = 1
QUIZ_INCORRECT_PENALTY = float(PRODUCTION_CONFIG["quiz"]["incorrect_penalty"])
QUIZ_CLAIM_TIMEOUT_MINUTES = max(
    5,
    int(_locked_value(
        "QUIZ_CLAIM_TIMEOUT_MINUTES",
        PRODUCTION_CONFIG["scheduler"]["claim_timeout_minutes"],
    )),
)
QUIZ_JOB_LEASE_MINUTES = max(
    5, int(PRODUCTION_CONFIG["scheduler"]["dispatcher_lease_minutes"])
)
QUIZ_JOB_MAX_RETRIES = max(
    1, int(PRODUCTION_CONFIG["scheduler"]["dispatcher_max_retries"])
)
QUIZ_JOB_RETRY_BASE_SECONDS = max(
    10, int(PRODUCTION_CONFIG["scheduler"]["retry_base_seconds"])
)
QUIZ_JOB_RETRY_MAX_SECONDS = max(
    QUIZ_JOB_RETRY_BASE_SECONDS,
    int(PRODUCTION_CONFIG["scheduler"]["retry_max_seconds"]),
)
QUIZ_DISPATCH_INLINE_RETRY_MAX_PASSES = max(
    1, int(PRODUCTION_CONFIG["scheduler"]["inline_retry_max_passes"])
)
QUIZ_DISPATCH_INLINE_RETRY_WINDOW_SECONDS = max(
    0, int(PRODUCTION_CONFIG["scheduler"]["inline_retry_window_seconds"])
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
SCHEDULER_MIN_REUSE_GAP_DAYS = int(_locked_value(
    "SCHEDULER_MIN_REUSE_GAP_DAYS",
    PRODUCTION_CONFIG["scheduler"]["min_reuse_gap_days"],
))
SCHEDULER_MAX_REUSE_GAP_DAYS = int(_locked_value(
    "SCHEDULER_MAX_REUSE_GAP_DAYS",
    PRODUCTION_CONFIG["scheduler"]["max_reuse_gap_days"],
))

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


def gemini_provider_configuration() -> tuple[bool, bool]:
    """Return key availability without ever returning or logging key values."""
    primary = bool(
        os.environ.get("GEMINI_API_KEY_PRIMARY")
        or os.environ.get("GEMINI_API_KEY")
    )
    secondary = bool(os.environ.get("GEMINI_API_KEY_SECONDARY"))
    return primary, secondary
