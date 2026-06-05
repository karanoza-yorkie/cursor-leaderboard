# Documentation Index

Technical documentation for the cursor-leaderboard project.

## Core

| Document | Description |
|----------|-------------|
| [architecture.md](./architecture.md) | System design, layers, deployment topology, security |
| [data-pipeline.md](./data-pipeline.md) | Weekly ETL: download → merge → analysis → HTML |
| [getting-started.md](./getting-started.md) | Local setup, run pipeline, TV, and live overlay |
| [configuration.md](./configuration.md) | Environment variables, secrets, dependencies |

## Realtime / Live Overlay

| Document | Description |
|----------|-------------|
| [face-detection.md](./face-detection.md) | Phone → backend → TV flow, browser compatibility |
| [api-reference.md](./api-reference.md) | FastAPI REST + WebSocket protocol |
| [../backend/README.md](../backend/README.md) | Backend quick start, HTTPS, LAN testing |

## Key Source Files

| Area | Files |
|------|-------|
| Pipeline | `src/pipeline.py`, `src/downloader.py`, `src/merge_data.py`, `src/analysis.py`, `src/generate_leaderboard.py` |
| Backend | `backend/main.py`, `backend/recognition.py`, `backend/activity_client.py` |
| Frontend | `frontend/phone.html`, generated `output/latest/leaderboard.html` |
| CI | `.github/workflows/pipeline.yml`, `daily_job.sh` |

## Quick Links

- **Run pipeline:** `python src/pipeline.py`
- **Run backend:** `uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000`
- **TV page:** `output/latest/leaderboard.html?ws=ws://localhost:8000/ws`
- **Phone page:** `http://localhost:8000/phone`
