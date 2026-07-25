"""Supabase client singleton.

Every repo module in storage/ imports get_client() from here rather than
constructing its own client, so the whole process shares one connection
and the Supabase URL/key are validated in exactly one place.
"""

from __future__ import annotations

from functools import lru_cache

from config.settings import require_env, supabase_project_ref_matches
from errors import ConfigurationError
from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = require_env("SUPABASE_URL")
    key = require_env("SUPABASE_SERVICE_KEY")
    expected_ref = require_env("EXPECTED_SUPABASE_PROJECT_REF")
    if not supabase_project_ref_matches(url, expected_ref):
        raise ConfigurationError(
            "Supabase URL does not match EXPECTED_SUPABASE_PROJECT_REF."
        )
    return create_client(url, key)
