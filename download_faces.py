#!/usr/bin/env python3
"""
Download active employee profile images into data/faces/ for face recognition.

Requires EXTERNAL_API_SECRET (York Hub external API key):

    export EXTERNAL_API_SECRET=your_key_here
    python download_faces.py

Optional: python download_faces.py --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

USERS_URL = "https://api.hub.york.ie/api/external/users/active"
REPO_ROOT = Path(__file__).resolve().parent
FACES_DIR = REPO_ROOT / "data" / "faces"
SRC_DIR = REPO_ROOT / "src"
REQUEST_TIMEOUT = (10, 30)  # (connect, read) seconds

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils import get_last_7_days_range  # noqa: E402

_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_NAME_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]*$")

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sanitize_name_segment(raw: str) -> str:
    """Lowercase slug safe for recognition filename prefix."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9.\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _is_valid_name_prefix(name: str) -> bool:
    return bool(name) and _NAME_PREFIX_RE.match(name) is not None


def normalize_name(name: str, email: str) -> str | None:
    """
    "Nilesh Sukhwani" → "nilesh-sukhwani".
    Falls back to email local-part if display name cannot be sanitized.
    """
    candidates: list[str] = []

    if name and name.strip():
        spaced = "-".join(name.strip().lower().split())
        candidates.append(_sanitize_name_segment(spaced))

    if email and "@" in email:
        local = email.strip().lower().split("@", 1)[0]
        candidates.append(_sanitize_name_segment(local))

    for candidate in candidates:
        if _is_valid_name_prefix(candidate):
            return candidate
    return None


def extension_from_url(url: str) -> str:
    """Return .jpg, .jpeg, or .png from URL path; default .jpg."""
    path = urlparse(url).path.lower()
    for ext in (".jpeg", ".jpg", ".png"):
        if path.endswith(ext):
            return ext
    return ".jpg"


def fetch_active_users(api_key: str) -> list[dict]:
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }
    try:
        res = requests.get(USERS_URL, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.error("Failed to fetch active users: %s", exc)
        raise SystemExit(1) from exc

    if res.status_code != 200:
        logger.error(
            "Active users API returned HTTP %s: %s",
            res.status_code,
            res.text[:500],
        )
        raise SystemExit(1)

    try:
        body = res.json()
    except ValueError as exc:
        logger.error("Active users response is not JSON: %s", exc)
        raise SystemExit(1) from exc

    if not body.get("success"):
        logger.error("Active users API success=false: %s", body)
        raise SystemExit(1)

    data = body.get("data")
    if not isinstance(data, dict):
        logger.error("Active users API missing data object: %s", body)
        raise SystemExit(1)

    users = data.get("users")
    if not isinstance(users, list):
        logger.error("Active users API data.users is not a list: %s", body)
        raise SystemExit(1)

    return users


def download_image(url: str, api_key: str) -> bytes | None:
    """GET image bytes; retry once with x-api-key on 401/403."""
    headers: dict[str, str] = {}

    def _get(hdrs: dict[str, str]) -> requests.Response:
        return requests.get(url, headers=hdrs, timeout=REQUEST_TIMEOUT)

    try:
        res = _get(headers)
        if res.status_code in (401, 403):
            res = _get({"x-api-key": api_key})
    except requests.RequestException as exc:
        logger.debug("Image request error for %s: %s", _truncate_url(url), exc)
        return None

    if res.status_code != 200:
        logger.debug(
            "Image HTTP %s for %s",
            res.status_code,
            _truncate_url(url),
        )
        return None

    if not res.content:
        return None
    return res.content


def _truncate_url(url: str, max_len: int = 80) -> str:
    if len(url) <= max_len:
        return url
    return url[: max_len - 3] + "..."


def process_user(user: dict, api_key: str, faces_dir: Path) -> str:
    """
    Download one user image. Returns outcome: 'ok', 'skip', or 'fail'.
    """
    if not isinstance(user, dict):
        logger.warning("SKIP invalid user record (not an object)")
        return "skip"

    email = (user.get("email") or "").strip()
    name = (user.get("name") or "").strip()
    profile_image = (user.get("profile_image") or "").strip()

    if not email:
        logger.info("SKIP unknown: missing email")
        return "skip"
    if not name:
        logger.info("SKIP %s: missing name", email)
        return "skip"
    if not profile_image:
        logger.info("SKIP %s: missing profile_image", email)
        return "skip"
    if "@" not in email:
        logger.info("SKIP %s: invalid email", email)
        return "skip"

    normalized = normalize_name(name, email)
    if not normalized:
        logger.info("SKIP %s: could not normalize name %r", email, name)
        return "skip"

    ext = extension_from_url(profile_image)
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        ext = ".jpg"

    filename = f"{normalized}_{email.lower()}{ext}"
    dest = faces_dir / filename

    image_bytes = download_image(profile_image, api_key)
    if image_bytes is None:
        logger.warning(
            "FAIL %s: could not download image (%s)",
            email,
            _truncate_url(profile_image),
        )
        return "fail"

    dest.write_bytes(image_bytes)
    logger.info("OK %s → %s", email, dest.relative_to(REPO_ROOT))
    return "ok"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download active employee profile images into data/faces/",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging (image URLs truncated in logs)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    api_key = os.getenv("EXTERNAL_API_SECRET", "").strip()
    if not api_key:
        logger.error(
            "EXTERNAL_API_SECRET is not set. "
            "Export your York Hub external API key before running."
        )
        raise SystemExit(1)

    FACES_DIR.mkdir(parents=True, exist_ok=True)
    start, end = get_last_7_days_range()
    logger.info("Active leaderboard date range: %s → %s", start, end)
    logger.info("Saving faces to %s", FACES_DIR)

    users = fetch_active_users(api_key)
    total = len(users)
    downloaded = skipped = failed = 0

    for user in users:
        outcome = process_user(user, api_key, FACES_DIR)
        if outcome == "ok":
            downloaded += 1
        elif outcome == "skip":
            skipped += 1
        else:
            failed += 1

    logger.info(
        "done: downloaded=%d skipped=%d failed=%d total=%d",
        downloaded,
        skipped,
        failed,
        total,
    )


if __name__ == "__main__":
    main()
