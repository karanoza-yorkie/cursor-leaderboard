"""Date-range and pipeline path helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from utils import get_last_7_days_range, get_week_folder  # noqa: E402


def get_week() -> tuple[str, str]:
    """Rolling 7-day window ending yesterday (inclusive).

    Returns ``(startDate, endDate)`` as ISO ``YYYY-MM-DD`` strings.
    """
    start, end = get_last_7_days_range()
    return start.isoformat(), end.isoformat()


def get_pipeline_week_folder() -> str:
    """Processed-data folder name for the rolling last-7-days window."""

    return get_week_folder()


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
