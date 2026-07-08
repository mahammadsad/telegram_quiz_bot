"""ISO-8601 week number helper.

Used to tag every generated question with the week it was created
(questions.week_number), which feeds the scheduler's "balanced
distribution across weeks" requirement and is handy for analytics later.
"""

from __future__ import annotations

from datetime import date


def iso_week_number(on_date: date | None = None) -> int:
    """Return the ISO-8601 week number (1-53) for the given date (default: today)."""
    d = on_date or date.today()
    return d.isocalendar()[1]
