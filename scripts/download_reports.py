"""
download_reports.py
====================
Logs into the Cursor dashboard using Playwright (headless Chromium),
navigates to the Team Usage and User Leaderboard pages, and downloads
the CSV exports to data/raw/.

Required environment variables:
  CURSOR_EMAIL      – your Cursor admin email
  CURSOR_PASSWORD   – your Cursor admin password

Outputs (paths match what merge_data.py expects):
  data/raw/team-usage-events-<start>_<end>.csv
  data/raw/User_Leaderboard_<start>_<end>.csv
"""

import os
import logging
import time
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
CURSOR_EMAIL    = os.environ["CURSOR_EMAIL"]
CURSOR_PASSWORD = os.environ["CURSOR_PASSWORD"]

# Date range: Mon → Fri of the previous week
today = datetime.utcnow().date()
last_monday = today - timedelta(days=today.weekday() + 7)
last_friday  = last_monday + timedelta(days=4)

START_DATE = last_monday.strftime("%Y-%m-%d")
END_DATE   = last_friday.strftime("%Y-%m-%d")

START_LABEL = last_monday.strftime("%-d%b").capitalize()   # e.g. "20Apr"
END_LABEL   = last_friday.strftime("%-d%b").capitalize()   # e.g. "24Apr"

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

CURSOR_BASE_URL = "https://www.cursor.com"

TEAM_USAGE_DEST  = RAW_DIR / f"team-usage-events-{START_LABEL}_{END_LABEL}.csv"
LEADERBOARD_DEST = RAW_DIR / f"User_Leaderboard_{START_LABEL}_{END_LABEL}.csv"

# ── Helpers ────────────────────────────────────────────────────────────────────

def wait_for_download(page, trigger_fn, download_dir: Path, timeout: int = 60_000):
    """Click something, wait for a download to complete, return the Path."""
    with page.expect_download(timeout=timeout) as dl_info:
        trigger_fn()
    download = dl_info.value
    tmp = Path(download.path())
    dest = download_dir / download.suggested_filename
    shutil.move(str(tmp), str(dest))
    log.info("  → saved to %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def set_date_range(page, start: str, end: str):
    """
    Fill in the date range pickers on the Cursor analytics pages.
    Cursor uses <input type="date"> fields.  Adjust selectors if the UI changes.
    """
    log.info("  Setting date range %s → %s", start, end)
    start_input = page.locator('input[placeholder*="start" i], input[name*="start" i], input[aria-label*="start" i]').first
    end_input   = page.locator('input[placeholder*="end" i], input[name*="end" i], input[aria-label*="end" i]').first
    start_input.fill(start)
    end_input.fill(end)
    # Press Enter or click Apply to trigger re-query
    apply_btn = page.locator('button:has-text("Apply"), button:has-text("Filter")').first
    if apply_btn.count():
        apply_btn.click()
    else:
        end_input.press("Enter")
    page.wait_for_load_state("networkidle", timeout=30_000)


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Cursor report downloader starting")
    log.info("Date range: %s → %s", START_DATE, END_DATE)
    log.info("Output dir: %s", RAW_DIR.resolve())
    log.info("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        # ── Login ──────────────────────────────────────────────────────────
        log.info("Navigating to Cursor login...")
        page.goto(f"{CURSOR_BASE_URL}/login", wait_until="networkidle")

        # Fill email
        page.locator('input[type="email"], input[name="email"]').fill(CURSOR_EMAIL)
        page.keyboard.press("Tab")

        # Fill password
        page.locator('input[type="password"], input[name="password"]').fill(CURSOR_PASSWORD)
        page.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")').first.click()

        try:
            page.wait_for_url("**/dashboard**", timeout=30_000)
            log.info("✅ Logged in successfully")
        except PWTimeout:
            # Some orgs use SSO or email magic link — log what we see and fail clearly
            log.error("Login timeout. Current URL: %s", page.url)
            page.screenshot(path="login_failure.png")
            raise RuntimeError(
                "Could not log in to Cursor. Check CURSOR_EMAIL / CURSOR_PASSWORD secrets, "
                "or the login page structure may have changed. Screenshot saved: login_failure.png"
            )

        # ── Download 1: Team Usage Events ──────────────────────────────────
        log.info("Navigating to Team Usage Events page...")
        page.goto(f"{CURSOR_BASE_URL}/dashboard/team-usage", wait_until="networkidle")
        time.sleep(2)  # let JS hydrate

        set_date_range(page, START_DATE, END_DATE)

        log.info("Downloading Team Usage CSV...")
        try:
            team_csv = wait_for_download(
                page,
                trigger_fn=lambda: page.locator(
                    'button:has-text("Export"), button:has-text("Download"), a:has-text("CSV")'
                ).first.click(),
                download_dir=RAW_DIR,
            )
            # Rename to expected filename
            shutil.move(str(team_csv), str(TEAM_USAGE_DEST))
            log.info("✅ Team Usage saved: %s", TEAM_USAGE_DEST)
        except Exception as exc:
            page.screenshot(path="team_usage_failure.png")
            raise RuntimeError(f"Failed to download Team Usage CSV: {exc}") from exc

        # ── Download 2: User Leaderboard ───────────────────────────────────
        log.info("Navigating to User Leaderboard page...")
        page.goto(f"{CURSOR_BASE_URL}/dashboard/leaderboard", wait_until="networkidle")
        time.sleep(2)

        set_date_range(page, START_DATE, END_DATE)

        log.info("Downloading User Leaderboard CSV...")
        try:
            lb_csv = wait_for_download(
                page,
                trigger_fn=lambda: page.locator(
                    'button:has-text("Export"), button:has-text("Download"), a:has-text("CSV")'
                ).first.click(),
                download_dir=RAW_DIR,
            )
            shutil.move(str(lb_csv), str(LEADERBOARD_DEST))
            log.info("✅ Leaderboard saved: %s", LEADERBOARD_DEST)
        except Exception as exc:
            page.screenshot(path="leaderboard_failure.png")
            raise RuntimeError(f"Failed to download Leaderboard CSV: {exc}") from exc

        browser.close()

    log.info("=" * 60)
    log.info("All reports downloaded successfully")
    log.info("  %s", TEAM_USAGE_DEST)
    log.info("  %s", LEADERBOARD_DEST)
    log.info("=" * 60)

    # Write a manifest so downstream scripts can find the exact filenames
    manifest = RAW_DIR / "latest_files.env"
    manifest.write_text(
        f"TEAM_USAGE_FILE={TEAM_USAGE_DEST}\n"
        f"LEADERBOARD_FILE={LEADERBOARD_DEST}\n"
        f"START_DATE={START_DATE}\n"
        f"END_DATE={END_DATE}\n"
    )
    log.info("Manifest written: %s", manifest)


if __name__ == "__main__":
    run()
