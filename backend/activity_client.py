"""
Async client for the York daily-activity API.

Aggregates per-user metrics for a rolling week. On partial failure,
missing fields are returned as ``"-"`` (except ``activeDays`` which
defaults to ``0``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, TypedDict, Union

import httpx

from week_utils import get_week

logger = logging.getLogger(__name__)

DAILY_ACTIVITY_URL: str = os.getenv(
    "DAILY_ACTIVITY_URL",
    "https://prompts.yorkdevs.link/api/v1/users/daily-activity",
)
# Required secret: fail fast if missing to prevent silent insecure defaults.
DAILY_ACTIVITY_API_KEY: str = os.environ["DAILY_ACTIVITY_API_KEY"]
ACTIVITY_TIMEOUT_SEC: float = float(os.getenv("ACTIVITY_TIMEOUT_SEC", "5"))


class Metrics(TypedDict):
    totalAiLines: Union[int, str]
    promptCount: Union[int, str]
    avgScore: Union[float, str]
    activeDays: int
    usageScore: str


def _empty_metrics() -> Metrics:
    return {
        "totalAiLines": "-",
        "promptCount": "-",
        "avgScore": "-",
        "activeDays": 0,
        "usageScore": "-",
    }


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("data"), list):
        return [r for r in payload["data"] if isinstance(r, dict)]
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return [r for r in result["items"] if isinstance(r, dict)]
    return []


def _row_value(row: dict[str, Any], *candidates: str) -> Any:
    lower_map = {k.lower(): v for k, v in row.items()}
    for key in candidates:
        if key in row:
            return row[key]
        val = lower_map.get(key.lower())
        if val is not None:
            return val
    return None


def _aggregate_rows(rows: list[dict[str, Any]]) -> Metrics:
    if not rows:
        return _empty_metrics()

    total_ai = 0
    total_prompts = 0
    scores: list[float] = []
    ai_ok = False
    prompt_ok = False

    for row in rows:
        raw_ai = _row_value(row, "totalAiLines", "total_ai_lines")
        if raw_ai is not None:
            try:
                total_ai += int(float(raw_ai))
                ai_ok = True
            except (TypeError, ValueError):
                pass

        raw_prompt = _row_value(row, "promptCount", "prompt_count")
        if raw_prompt is not None:
            try:
                total_prompts += int(float(raw_prompt))
                prompt_ok = True
            except (TypeError, ValueError):
                pass

        raw_score = _row_value(row, "avgScore", "avg_score")
        if raw_score is not None:
            try:
                scores.append(float(raw_score))
            except (TypeError, ValueError):
                pass

    metrics: Metrics = {
        "totalAiLines": total_ai if ai_ok else "-",
        "promptCount": total_prompts if prompt_ok else "-",
        "avgScore": round(sum(scores) / len(scores), 2) if scores else "-",
        "activeDays": len(rows),
        "usageScore": "-",
    }
    return metrics


def aggregate_daily_activity(payload: Any) -> Metrics:
    """Parse API JSON and aggregate metrics for a single-email response."""

    rows = _extract_rows(payload)
    return _aggregate_rows(rows)


async def fetch_daily_metrics(email: str) -> Metrics:
    """POST daily-activity for ``email`` and return aggregated metrics."""

    start_date, end_date = get_week()
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "email": [email],
    }
    headers = {
        "x-api-key": DAILY_ACTIVITY_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=ACTIVITY_TIMEOUT_SEC) as client:
            response = await client.post(
                DAILY_ACTIVITY_URL,
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Daily activity API request failed for %s: %s", email, exc)
        return _empty_metrics()
    except ValueError as exc:
        logger.warning("Daily activity API returned invalid JSON for %s: %s", email, exc)
        return _empty_metrics()

    return aggregate_daily_activity(payload)
