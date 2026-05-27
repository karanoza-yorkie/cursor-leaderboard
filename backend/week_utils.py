"""Date-range helpers for the daily-activity API."""

from __future__ import annotations

from datetime import date, timedelta


def get_week() -> tuple[str, str]:
    """Rolling 7-day window ending today (inclusive).

    Returns ``(startDate, endDate)`` as ISO ``YYYY-MM-DD`` strings.
    """

    end = date.today()
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()
