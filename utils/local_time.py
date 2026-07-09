"""Timezone helpers for date-based quiz IDs."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.settings import APP_TIMEZONE


def local_today() -> date:
    try:
        return datetime.now(ZoneInfo(APP_TIMEZONE)).date()
    except ZoneInfoNotFoundError:
        return date.today()
