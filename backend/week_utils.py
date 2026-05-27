"""Date-range and pipeline path helpers."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path


def get_week() -> tuple[str, str]:
    """Rolling 7-day window ending today (inclusive).

    Returns ``(startDate, endDate)`` as ISO ``YYYY-MM-DD`` strings.
    """

    end = date.today()
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


def get_pipeline_week_folder() -> str:
    """Week folder name used by ``src/analysis.py`` (last Mon–Fri block)."""

    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return f"{last_monday}_{last_friday}"


def resolve_all_users_csv(repo_root: Path) -> Path:
    """Path to ``all_users.csv`` — override via ``ALL_USERS_CSV`` or pipeline week."""

    override = os.getenv("ALL_USERS_CSV", "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else repo_root / path
    return (
        repo_root
        / "data"
        / "processed"
        / get_pipeline_week_folder()
        / "all_users.csv"
    )
