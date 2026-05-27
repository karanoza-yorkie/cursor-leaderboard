"""
Load per-user leaderboard metrics from pipeline-generated ``all_users.csv``.

No external API calls at runtime — the CSV is the single source of truth for
live detection cards.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional, TypedDict, Union

from week_utils import resolve_all_users_csv

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

_index_cache: dict[str, "Metrics"] | None = None
_index_mtime: float | None = None
_index_path: Path | None = None


class Metrics(TypedDict):
    """Fields consumed by the TV live overlay (``fillLiveSlide``)."""

    totalAiLines: Union[int, float, str]
    promptCount: Union[int, float, str]
    avgScore: Union[int, float, str]
    activeDays: int
    usageScore: Union[int, float, str]
    finalScore: Union[int, float, str]
    rank: int


def _cell(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return "-"


def _active_days(row: dict[str, str]) -> int:
    raw = _cell(row, "Active_Days")
    if raw == "-":
        return 0
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return 0


def _row_email(row: dict[str, str]) -> Optional[str]:
    for key in ("Email", "email"):
        raw = row.get(key, "").strip()
        if raw and "@" in raw:
            return raw.lower()
    return None


def _final_score_sort_key(row: dict[str, str]) -> float:
    raw = row.get("final_score", "")
    try:
        return float(raw) if raw not in (None, "") else 0.0
    except (ValueError, TypeError):
        return 0.0


def _row_to_metrics(row: dict[str, str], rank: int) -> Metrics:
    """Map one CSV row to the WS payload metrics object (no recalculation)."""

    return {
        "totalAiLines": _cell(row, "Total_AI_Lines"),
        "promptCount": _cell(row, "Total_Prompts", "total_prompts"),
        "avgScore": _cell(row, "quality_score"),
        "activeDays": _active_days(row),
        "usageScore": _cell(row, "usage_score"),
        "finalScore": _cell(row, "final_score"),
        "rank": rank,
    }


def _load_index() -> dict[str, Metrics]:
    """Load or reload the email → metrics index when the CSV file changes."""

    global _index_cache, _index_mtime, _index_path

    path = resolve_all_users_csv(REPO_ROOT)
    if not path.is_file():
        logger.warning("all_users.csv not found at %s", path)
        _index_cache = {}
        _index_mtime = None
        _index_path = path
        return {}

    mtime = path.stat().st_mtime
    if (
        _index_cache is not None
        and _index_path == path
        and _index_mtime == mtime
    ):
        return _index_cache

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    ranked = sorted(rows, key=_final_score_sort_key, reverse=True)
    index: dict[str, Metrics] = {}
    for rank, row in enumerate(ranked, start=1):
        email = _row_email(row)
        if not email or email in index:
            continue
        index[email] = _row_to_metrics(row, rank)

    _index_cache = index
    _index_mtime = mtime
    _index_path = path
    logger.info("Loaded %d users from %s", len(index), path)
    return index


def preload_metrics_index() -> Path:
    """Warm the CSV index at startup; returns the resolved CSV path."""

    path = resolve_all_users_csv(REPO_ROOT)
    _load_index()
    return path


def fetch_daily_metrics(email: str) -> Optional[Metrics]:
    """Look up precomputed metrics by email. Returns ``None`` if not in CSV."""

    if not email or "@" not in email:
        return None
    key = email.strip().lower()
    metrics = _load_index().get(key)
    if metrics is None:
        logger.info("metrics_not_found email=%s", key)
    return metrics
