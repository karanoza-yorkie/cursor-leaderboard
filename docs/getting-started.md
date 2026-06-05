# Getting Started

Quick setup for running the weekly pipeline, TV display, and live face-detection overlay locally.

## Prerequisites

- **Python 3.11** (recommended; matches CI)
- **CMake** (for `face_recognition` / dlib): `brew install cmake` on macOS
- **Git**
- API keys: `HUB_API_KEY`, `DAILY_ACTIVITY_API_KEY` (see [configuration.md](./configuration.md))
- **Cursor session file:** `state_fixed.json` at repo root (Playwright storage state)

---

## 1. Clone and Install

```bash
git clone <repo-url>
cd cursor_leaderboard

# Pipeline dependencies
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Backend dependencies (for live overlay)
pip install -r backend/requirements.txt
```

---

## 2. Configure Environment

Create `.env` at the repo root (for `daily_job.sh`):

```bash
HUB_API_KEY=your_key_here
DAILY_ACTIVITY_API_KEY=your_key_here
EXTERNAL_API_SECRET=your_key_here   # optional, for download_faces.py
```

For a one-off pipeline run:

```bash
export HUB_API_KEY=...
export DAILY_ACTIVITY_API_KEY=...
```

Place `state_fixed.json` in the repo root. In CI this is restored from the `CURSOR_STATE` GitHub Secret.

---

## 3. Run the Weekly Pipeline

```bash
python src/pipeline.py
```

This executes: download → merge → analysis → generate HTML.

**Outputs:**

- `data/processed/{week}/top10.csv`, `all_users.csv`
- `output/latest/leaderboard.html`
- `output/history/{week}.html`

Or use the wrapper script (pipeline + face download):

```bash
chmod +x daily_job.sh
./daily_job.sh
```

---

## 4. View the Leaderboard (TV)

Open the generated file in a browser:

```bash
open output/latest/leaderboard.html
```

For GitHub Pages equivalent:

```bash
open docs/index.html
```

The page auto-refreshes every 5 minutes and rotates Top-10 slides every 6 seconds.

---

## 5. Live Face-Detection Overlay

### 5a. Sync face photos (first time)

```bash
export EXTERNAL_API_SECRET=your_key
python download_faces.py
```

Photos are saved to `data/faces/` as `{name}_{email}.png`.

### 5b. Start the backend

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

Verify:

```bash
curl http://localhost:8000/health
# {"ok": true, "connections": 0}
```

Ensure `data/processed/{week}/all_users.csv` exists (from pipeline step 3).

### 5c. Open the phone page

**Same machine (localhost):**

```bash
open http://localhost:8000/phone
```

**Real phone on LAN:** Camera requires HTTPS. Use a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
# Open the printed https:// URL on your phone → /phone
```

### 5d. Connect the TV to WebSocket

Open the leaderboard with a WebSocket query param pointing at your backend:

```
file:///.../output/latest/leaderboard.html?ws=ws://localhost:8000/ws
```

Or from GitHub Pages (requires `wss://`):

```
https://<org>.github.io/<repo>/?ws=wss://your-tunnel.example/ws
```

### 5e. Test detection manually

```bash
curl -X POST http://localhost:8000/detect \
  -F "image=@data/faces/some-user_email@york.ie.png"
```

When a match is found and metrics exist in CSV, connected TVs receive a `PERSON_DETECTED` WebSocket event.

---

## 6. GitHub Actions (CI)

The workflow runs automatically every **Monday 10:00 UTC** or via **workflow_dispatch**.

Required repository secrets:

- `HUB_API_KEY`
- `DAILY_ACTIVITY_API_KEY`
- `CURSOR_STATE`

After a successful run, `docs/index.html` is updated and committed for GitHub Pages.

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|--------------|-----|
| Pipeline fails at download | Missing/expired `state_fixed.json` | Re-export Cursor session; update `CURSOR_STATE` secret |
| `HUB_API_KEY` / `DAILY_ACTIVITY_API_KEY` error | Env not set | Export vars or use `.env` + `daily_job.sh` |
| Backend won't start | Empty `data/faces/` | Run `download_faces.py` or set `REQUIRE_KNOWN_FACES=0` |
| Phone shows "HTTPS required" | Plain HTTP from LAN IP | Use `cloudflared` or mkcert (see [backend/README.md](../backend/README.md)) |
| TV never shows live slide | Wrong HTML file or WS URL | Use `output/latest/` or `docs/index.html` with `?ws=` param |
| Mixed content blocked | HTTPS page + `ws://` | Use `wss://` tunnel URL in `?ws=` |
| Live metrics missing | Email not in `all_users.csv` | Re-run pipeline; check week folder matches backend |

Enable TV debug logging: add `?live_debug=1` to the leaderboard URL.

---

## Next Steps

- [architecture.md](./architecture.md) — system design overview
- [data-pipeline.md](./data-pipeline.md) — ETL and scoring detail
- [api-reference.md](./api-reference.md) — FastAPI routes and WebSocket protocol
- [face-detection.md](./face-detection.md) — live overlay design and browser compatibility
