# Configuration Reference

Environment variables, secrets, and runtime settings for the batch pipeline and FastAPI backend.

## GitHub Secrets (CI)

Required by `.github/workflows/pipeline.yml`:

| Secret | Used by | Purpose |
|--------|---------|---------|
| `HUB_API_KEY` | `src/generate_leaderboard.py` | York Hub profile picture API (optional fetch path) |
| `DAILY_ACTIVITY_API_KEY` | `src/analysis.py` | Prompt quality API for scoring |
| `CURSOR_STATE` | Workflow step | Base64-encoded Playwright `storage_state` → `state_fixed.json` |

Optional for face roster sync in CI:

| Secret | Used by | Purpose |
|--------|---------|---------|
| `EXTERNAL_API_SECRET` | `download_faces.py` | York Hub active users + profile images |

---

## Local `.env` File

Used by `daily_job.sh` (not loaded automatically by `pipeline.py` or uvicorn).

```bash
HUB_API_KEY=your_hub_key
DAILY_ACTIVITY_API_KEY=your_daily_activity_key
EXTERNAL_API_SECRET=your_hub_external_key
```

**Never commit `.env`.** It is listed in `.gitignore` patterns for secrets; keep keys in GitHub Secrets for CI.

---

## Pipeline Environment Variables

| Variable | Required | Default | Module | Purpose |
|----------|----------|---------|--------|---------|
| `HUB_API_KEY` | Yes | — | `generate_leaderboard.py` | York Hub API auth |
| `DAILY_ACTIVITY_API_KEY` | Yes | — | `analysis.py` | Daily Activity API auth |

Pipeline modules read these via `os.environ[...]` and fail fast if missing.

---

## Backend Environment Variables

All are optional; defaults allow local development.

| Variable | Default | Purpose |
|----------|---------|---------|
| `COOLDOWN_SECONDS` | `10` | Per-email broadcast suppression window |
| `MAX_IMAGE_BYTES` | `5242880` (5 MB) | Max `/detect` payload size |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `FACES_DIR` | `data/faces` | Reference photos directory |
| `FACE_MATCH_THRESHOLD` | `0.45` in code / `0.6` in README | Max face distance for match (lower = stricter) |
| `FACE_DETECT_MODEL` | `hog` | dlib detector: `hog` (CPU) or `cnn` (GPU) |
| `REQUIRE_KNOWN_FACES` | `1` | Refuse startup if face roster is empty |
| `ALL_USERS_CSV` | `data/processed/{week}/all_users.csv` | Metrics CSV for live detections |

> **Note:** `FACE_MATCH_THRESHOLD` default is `0.45` in `backend/main.py` but documented as `0.6` in `backend/README.md`. Override explicitly in production.

---

## TV / Live Overlay Configuration

The WebSocket URL is resolved **at runtime** in the generated HTML (not baked in at build time):

1. `?ws=` query parameter on the page URL — highest priority  
   Example: `leaderboard.html?ws=wss://your-host/ws`
2. `window.LEADERBOARD_WS_URL` global (set via script tag or DevTools)
3. Fallback default: `wss://cursor-leaderboard.yorkdevs.link/ws`

Debug mode: append `?live_debug=1` to log overlay events in the browser console.

---

## `daily_job.sh` Settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `PYTHON_BIN` | `python3` | Python interpreter |
| `LOG_RETENTION_DAYS` | `30` | Delete `logs/*.log` older than N days (`0` = disable) |

---

## Static Files & Session

| File | Purpose |
|------|---------|
| `state_fixed.json` | Playwright session for Cursor dashboard (required for download step) |
| `data/raw/employee_list.csv` | Employee roster for merges |

Both are required for a full pipeline run. Session file is gitignored (`state_fixed.json` in `.gitignore`).

---

## Dependency Files

| File | Install command | Used for |
|------|-----------------|----------|
| `requirements.txt` | `pip install -r requirements.txt` | Pipeline: playwright, pandas, requests |
| `backend/requirements.txt` | `pip install -r backend/requirements.txt` | FastAPI, uvicorn, face_recognition |

After installing pipeline deps, run `playwright install` for Chromium.

**Recommended Python:** 3.11 (matches GitHub Actions; best dlib compatibility).

---

## Security Checklist

- [ ] `.env` not tracked in git
- [ ] GitHub Secrets set for CI variables
- [ ] `ALLOWED_ORIGINS` restricted in production (not `*`)
- [ ] Backend behind HTTPS / WSS when TV loads from GitHub Pages
- [ ] `state_fixed.json` rotated if Cursor session expires
