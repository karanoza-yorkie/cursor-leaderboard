from datetime import datetime, timedelta
import os

def get_last_week_range():
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday, last_friday

def get_week_folder():
    start, end = get_last_week_range()
    return f"{start}_{end}"

def ensure_dirs():
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("output/latest", exist_ok=True)
    os.makedirs("output/history", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
