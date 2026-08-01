"""Authoritative application-to-database contract identifiers.

Only this module may define the required migration or contract version. Health,
preflight, documentation tests, and deployment code import these values.
"""

from __future__ import annotations

APPLICATION_VERSION = "7.2.3"
DATABASE_CONTRACT_KEY = "telegram_quiz_api"
DATABASE_CONTRACT_VERSION = "2.2.0"
REQUIRED_MIGRATION_VERSION = "20260724212939"
SOURCE_ROLLOUT_MIGRATION_VERSION = "20260728040209"
QUIZ_QUALITY_MIGRATION_VERSION = "20260728113750"
PERSONAL_LEARNING_MIGRATION_VERSION = "20260729134221"
LEADERBOARD_PRIVACY_MIGRATION_VERSION = "20260801045552"
