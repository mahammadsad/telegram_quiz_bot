"""Supabase client singleton.

Every repo module in storage/ imports get_client() from here rather than
constructing its own client, so the whole process shares one connection
and the Supabase URL/key are validated in exactly one place.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from config.settings import require_env


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = require_env("SUPABASE_URL")
    key = require_env("SUPABASE_SERVICE_KEY")
    return create_client(url, key)
