# import time
# import logging
# from pathlib import Path
# from datetime import datetime, timedelta
# from playwright.sync_api import sync_playwright

# logging.basicConfig(level=logging.INFO)
# log = logging.getLogger(__name__)

# STATE_FILE = "state_fixed.json"


# def get_last_week():
#     today = datetime.now().date()
#     last_monday = today - timedelta(days=today.weekday() + 7)
#     last_friday = last_monday + timedelta(days=4)
#     return last_monday, last_friday


# # ✅ NEW: dynamic folder
# def get_week_folder():
#     start, end = get_last_week()
#     return f"{start}_{end}"


# def set_date_range(page, start, end):
#     log.info(f"Setting date {start} → {end}")

#     page.locator("button:has-text('-')").first.click()
#     time.sleep(2)

#     calendar = page.locator("[role='grid']")

#     calendar.locator(f"button[role='gridcell']:has-text('{start.day}')").first.click()
#     time.sleep(1)

#     calendar.locator(f"button[role='gridcell']:has-text('{end.day}')").last.click()
#     time.sleep(1)

#     page.locator("button:has-text('Apply')").click()
#     time.sleep(3)


# def download_usage_leaderboard(page, file_path):
#     log.info("Waiting for all Download CSV buttons...")

#     page.wait_for_selector("button[aria-label='Download CSV']", timeout=60000)

#     buttons = page.locator("button[aria-label='Download CSV']")
#     count = buttons.count()

#     log.info(f"Found {count} download buttons")

#     if count < 5:
#         raise Exception(f"❌ Expected at least 5 buttons, found {count}")

#     leaderboard_btn = buttons.nth(4)

#     leaderboard_btn.scroll_into_view_if_needed()
#     page.wait_for_timeout(1000)

#     log.info("Clicking 5th Download CSV button (Usage Leaderboard)...")

#     with page.expect_download(timeout=60000) as dl:
#         leaderboard_btn.click()

#     dl.value.save_as(file_path)

#     log.info(f"✅ Leaderboard saved → {file_path}")


# def run_download():
#     start, end = get_last_week()

#     # ✅ NEW: dynamic folder
#     week_folder = get_week_folder()
#     RAW_DIR = Path(f"data/raw/{week_folder}")
#     RAW_DIR.mkdir(parents=True, exist_ok=True)

#     # ✅ NEW: fixed filenames (no overwrite issues across weeks)
#     usage_file = RAW_DIR / "usage.csv"
#     leaderboard_file = RAW_DIR / "leaderboard.csv"

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)

#         context = browser.new_context(
#             storage_state=STATE_FILE,
#             accept_downloads=True
#         )

#         page = context.new_page()

#         log.info("Opening dashboard...")
#         page.goto("https://cursor.sh/dashboard")

#         page.wait_for_selector("a:has-text('Analytics')", timeout=60000)
#         time.sleep(2)

#         log.info("Clicking Analytics...")
#         page.locator("a:has-text('Analytics')").first.click()

#         page.wait_for_selector("text=Usage Leaderboard", timeout=60000)
#         time.sleep(2)

#         set_date_range(page, start, end)

#         download_usage_leaderboard(page, leaderboard_file)

#         log.info("Clicking Usage tab...")
#         page.locator("a:has-text('Usage')").first.click()

#         page.wait_for_selector("button:has-text('Export')", timeout=60000)
#         time.sleep(2)

#         set_date_range(page, start, end)

#         log.info("Downloading usage CSV...")

#         with page.expect_download(timeout=60000) as dl:
#             page.locator("button:has-text('Export')").click()

#         dl.value.save_as(usage_file)

#         log.info(f"✅ Usage saved → {usage_file}")

#         browser.close()

#     log.info("🎉 DONE")


# if __name__ == "__main__":
#     run_download()




import time
import logging
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

from utils import get_last_7_days_range, get_week_folder

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = "state_fixed.json"


def get_last_week_test():
    # TEST MODE — swap to get_last_week_real() for production
    start = datetime(2026, 5, 3).date()
    end   = datetime(2026, 5, 6).date()
    return start, end


def get_calendar_month(page) -> datetime:
    """Read the currently displayed month from the open calendar picker."""
    cal = page.locator("div:has(button:has-text('Apply'))").first
    text = cal.locator("text=/^[A-Za-z]+\\s\\d{4}$/").first.text_content().strip()
    return datetime.strptime(text, "%B %Y")


def get_prev_next_buttons(page):
    """
    Returns (prev_btn, next_btn) by comparing bounding box x positions.
    The leftmost SVG arrow button = prev, rightmost = next.
    Works regardless of DOM order, which differs between Analytics and Usage tabs.
    """
    cal = page.locator("div:has(button:has-text('Apply'))").first
    arrow_buttons = cal.locator("button:has(svg)")

    count = arrow_buttons.count()
    if count < 2:
        raise Exception(f"Expected at least 2 arrow buttons, found {count}")

    # Collect all arrow buttons with their x position
    buttons_with_x = []
    for i in range(count):
        btn = arrow_buttons.nth(i)
        box = btn.bounding_box()
        if box:
            buttons_with_x.append((box["x"], btn))

    if len(buttons_with_x) < 2:
        raise Exception("Could not get bounding boxes for arrow buttons")

    buttons_with_x.sort(key=lambda t: t[0])   # sort by x: left → right

    prev_btn = buttons_with_x[0][1]    # leftmost  = ← prev
    next_btn = buttons_with_x[-1][1]   # rightmost = → next

    log.debug("prev_btn x=%.0f  next_btn x=%.0f",
              buttons_with_x[0][0], buttons_with_x[-1][0])

    return prev_btn, next_btn


def navigate_to_month(page, target: datetime):
    """Navigate the open calendar to `target` month using positional arrow detection."""
    for _ in range(24):   # safety cap
        current = get_calendar_month(page)
        log.info("Calendar: %s | Target: %s",
                 current.strftime("%B %Y"), target.strftime("%B %Y"))

        if current.year == target.year and current.month == target.month:
            return  # arrived

        prev_btn, next_btn = get_prev_next_buttons(page)

        if target > current:
            log.info("→ clicking next")
            next_btn.click()
        else:
            log.info("← clicking prev")
            prev_btn.click()

        page.wait_for_timeout(700)

    raise Exception(f"Could not navigate to {target.strftime('%B %Y')} after 24 attempts")


# def set_date_range(page, start, end):
#     log.info("Setting date range %s → %s", start, end)

#     # Open the date picker
#     page.locator("button:has-text('-')").first.click()
#     page.wait_for_timeout(2000)

#     # Select start date
#     navigate_to_month(page, datetime(start.year, start.month, 1))
#     page.get_by_role("gridcell", name=str(start.day), exact=True).first.click()
#     page.wait_for_timeout(1000)

#     # Select end date
#     navigate_to_month(page, datetime(end.year, end.month, 1))
#     page.get_by_role("gridcell", name=str(end.day), exact=True).first.click()
#     page.wait_for_timeout(1000)

#     # Apply
#     page.locator("button:has-text('Apply')").click()
#     page.wait_for_timeout(3000)
#     log.info("Date range applied")


def set_date_range(page, start, end):
    log.info(f"Setting date range {start} → {end}")

    # -------------------------
    # OPEN DATE PICKER
    # -------------------------
    page.locator("button:has-text('-')").first.click()
    page.wait_for_selector(".dashboard-date-picker", timeout=10000)

    calendar = page.locator(".dashboard-date-picker").first

    # -------------------------
    # SELECT START DATE (DOUBLE CLICK FIX)
    # -------------------------
    start_cells = calendar.locator(
        f"button[role='gridcell']:not([disabled]) >> text='{start.day}'"
    )

    if start_cells.count() == 0:
        raise Exception(f"❌ Could not find start date {start.day}")

    start_btn = start_cells.first

    # 🔥 CLICK TWICE (fix pre-selected range issue)
    start_btn.click()
    page.wait_for_timeout(200)
    # start_btn.click()
    # page.wait_for_timeout(500)

    # -------------------------
    # HANDLE CROSS-MONTH
    # -------------------------
    if start.month != end.month or start.year != end.year:
        log.info("Moving to next month for end date selection")

        next_arrow = page.locator("button[name='next-month']").first

        next_arrow.scroll_into_view_if_needed()
        next_arrow.click()
        page.wait_for_timeout(700)

        # re-fetch calendar after re-render
        calendar = page.locator(".dashboard-date-picker").first

    # -------------------------
    # SELECT END DATE
    # -------------------------
    end_cells = calendar.locator(
        f"button[role='gridcell']:not([disabled]) >> text='{end.day}'"
    )

    if end_cells.count() == 0:
        raise Exception(f"❌ Could not find end date {end.day}")

    end_cells.last.click()
    page.wait_for_timeout(500)

    # -------------------------
    # APPLY
    # -------------------------
    page.locator("button:has-text('Apply')").click()
    page.wait_for_timeout(2000)

    log.info("Date range applied")


def download_usage_leaderboard(page, file_path):
    log.info("Waiting for Download CSV buttons...")
    page.wait_for_selector("button[aria-label='Download CSV']", timeout=60000)

    buttons = page.locator("button[aria-label='Download CSV']")
    count = buttons.count()
    log.info("Found %d download buttons", count)

    if count < 5:
        raise Exception(f"Expected at least 5 'Download CSV' buttons, found {count}")

    leaderboard_btn = buttons.nth(4)
    leaderboard_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(1000)

    log.info("Clicking 5th Download CSV button (Usage Leaderboard)...")
    with page.expect_download(timeout=60000) as dl:
        leaderboard_btn.click()

    dl.value.save_as(file_path)
    log.info("Leaderboard saved: %s", file_path)


def run_download():
    start, end = get_last_7_days_range()

    start_label = start.strftime("%d%b")
    end_label   = end.strftime("%d%b")

    week_folder = get_week_folder()
    RAW_DIR = Path(f"data/raw/{week_folder}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    usage_file       = RAW_DIR / "usage.csv"
    leaderboard_file = RAW_DIR / "leaderboard.csv"

    log.info("Date range : %s → %s", start, end)
    log.info("team_usage → %s", usage_file)
    log.info("leaderboard→ %s", leaderboard_file)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=STATE_FILE,
            accept_downloads=True,
        )
        page = context.new_page()

        # Dashboard
        log.info("Opening dashboard...")
        page.goto("https://cursor.sh/dashboard")
        page.wait_for_selector("a:has-text('Analytics')", timeout=60000)
        time.sleep(2)

        # Analytics tab
        log.info("Clicking Analytics...")
        page.locator("a:has-text('Analytics')").first.click()
        page.wait_for_selector("text=Usage Leaderboard", timeout=60000)
        time.sleep(2)

        set_date_range(page, start, end)
        download_usage_leaderboard(page, leaderboard_file)

        # Usage tab
        log.info("Clicking Usage tab...")
        page.locator("a:has-text('Usage')").first.click()
        page.wait_for_selector("button:has-text('Export')", timeout=60000)
        time.sleep(2)

        set_date_range(page, start, end)

        log.info("Downloading team usage CSV...")
        with page.expect_download(timeout=60000) as dl:
            page.locator("button:has-text('Export')").first.click()

        dl.value.save_as(usage_file)
        log.info("Usage saved: %s", usage_file)

        browser.close()

    log.info("DONE — both files downloaded")


if __name__ == "__main__":
    run_download()
