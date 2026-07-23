"""Authoritative application-to-database contract identifiers.

Only this module may define the required migration or contract version. Health,
preflight, documentation tests, and deployment code import these values.
"""

from __future__ import annotations

APPLICATION_VERSION = "7.0.0"
DATABASE_CONTRACT_KEY = "telegram_quiz_api"
DATABASE_CONTRACT_VERSION = "2.2.0"
REQUIRED_MIGRATION_VERSION = "20260722120827"
