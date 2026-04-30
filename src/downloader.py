import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

STATE_FILE = "state_fixed.json"


def get_last_week():
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday, last_friday


# ✅ NEW: dynamic folder
def get_week_folder():
    start, end = get_last_week()
    return f"{start}_{end}"


def set_date_range(page, start, end):
    log.info(f"Setting date {start} → {end}")

    page.locator("button:has-text('-')").first.click()
    time.sleep(2)

    calendar = page.locator("[role='grid']")

    calendar.locator(f"button[role='gridcell']:has-text('{start.day}')").first.click()
    time.sleep(1)

    calendar.locator(f"button[role='gridcell']:has-text('{end.day}')").last.click()
    time.sleep(1)

    page.locator("button:has-text('Apply')").click()
    time.sleep(3)


def download_usage_leaderboard(page, file_path):
    log.info("Waiting for all Download CSV buttons...")

    page.wait_for_selector("button[aria-label='Download CSV']", timeout=60000)

    buttons = page.locator("button[aria-label='Download CSV']")
    count = buttons.count()

    log.info(f"Found {count} download buttons")

    if count < 5:
        raise Exception(f"❌ Expected at least 5 buttons, found {count}")

    leaderboard_btn = buttons.nth(4)

    leaderboard_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(1000)

    log.info("Clicking 5th Download CSV button (Usage Leaderboard)...")

    with page.expect_download(timeout=60000) as dl:
        leaderboard_btn.click()

    dl.value.save_as(file_path)

    log.info(f"✅ Leaderboard saved → {file_path}")


def run_download():
    start, end = get_last_week()

    # ✅ NEW: dynamic folder
    week_folder = get_week_folder()
    RAW_DIR = Path(f"data/raw/{week_folder}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ✅ NEW: fixed filenames (no overwrite issues across weeks)
    usage_file = RAW_DIR / "usage.csv"
    leaderboard_file = RAW_DIR / "leaderboard.csv"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        context = browser.new_context(
            storage_state=STATE_FILE,
            accept_downloads=True
        )

        page = context.new_page()

        log.info("Opening dashboard...")
        page.goto("https://cursor.sh/dashboard")

        page.wait_for_selector("a:has-text('Analytics')", timeout=60000)
        time.sleep(2)

        log.info("Clicking Analytics...")
        page.locator("a:has-text('Analytics')").first.click()

        page.wait_for_selector("text=Usage Leaderboard", timeout=60000)
        time.sleep(2)

        set_date_range(page, start, end)

        download_usage_leaderboard(page, leaderboard_file)

        log.info("Clicking Usage tab...")
        page.locator("a:has-text('Usage')").first.click()

        page.wait_for_selector("button:has-text('Export')", timeout=60000)
        time.sleep(2)

        set_date_range(page, start, end)

        log.info("Downloading usage CSV...")

        with page.expect_download(timeout=60000) as dl:
            page.locator("button:has-text('Export')").click()

        dl.value.save_as(usage_file)

        log.info(f"✅ Usage saved → {usage_file}")

        browser.close()

    log.info("🎉 DONE")


if __name__ == "__main__":
    run_download()
