from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import os

IST = ZoneInfo("Asia/Kolkata")


def get_last_7_days_range(tz: ZoneInfo = IST) -> tuple[date, date]:
    """Last 7 complete calendar days in ``tz``, excluding today.

    Returns ``(start_date, end_date)`` where:
    - ``end_date`` = yesterday (inclusive through 23:59:59)
    - ``start_date`` = end_date - 6 days (from 00:00:00)

    Stable for cron at any hour: boundaries are calendar dates in IST.
    """
    today = datetime.now(tz).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    return start, end


def get_week_folder() -> str:
    start, end = get_last_7_days_range()
    return f"{start}_{end}"


def ensure_dirs():
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("output/latest", exist_ok=True)
    os.makedirs("output/history", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
