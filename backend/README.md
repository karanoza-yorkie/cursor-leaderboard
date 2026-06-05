# Face Detection Backend

FastAPI service for the realtime face-detection → TV display layer.

**Documentation:** [docs/architecture.md](../docs/architecture.md) · [docs/api-reference.md](../docs/api-reference.md) · [docs/face-detection.md](../docs/face-detection.md)

## Prerequisites

The recognizer uses [`face_recognition`](https://github.com/ageitgey/face_recognition), which depends on `dlib`. `dlib` compiles from source on first install on most platforms — you need a C/C++ toolchain and CMake.

- **macOS**: `brew install cmake`
- **Debian/Ubuntu**: `sudo apt install -y cmake build-essential`
- **Windows**: install Visual Studio Build Tools + CMake, or use WSL with the Debian instructions.

**Recommended Python**: 3.11 (matches the GH Action's Python). dlib wheels for very new CPython versions are still patchy in 2026 — if 3.12+ works for you, great; if pip starts compiling for an hour, switch to 3.11.

## Quick start

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
# First install compiles dlib; takes a few minutes. Subsequent installs are cached.

.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

On startup the backend loads every `<name>_<email>.{jpg,jpeg,png}` from `data/faces/` (email is everything after the first `_`, must contain `@`), encodes each face once, and logs the roster. By default it refuses to start with an empty roster — set `REQUIRE_KNOWN_FACES=0` to override (e.g. for CI).

Live detection metrics are read from `data/processed/{week}/all_users.csv` (see `ALL_USERS_CSV` to override). No Daily Activity API call at runtime. Ensure the pipeline has generated `all_users.csv` for the current week folder.

- Phone: open `http://<host>:8000/phone`
- Health: `curl http://<host>:8000/health`
- Manually trigger a broadcast:

  ```bash
  curl -X POST http://localhost:8000/detect \
    -F "image=@/path/to/any.jpg"
  ```

## Environment variables

| Name                   | Default                  | Purpose                                                                                  |
| ---------------------- | ------------------------ | ---------------------------------------------------------------------------------------- |
| `COOLDOWN_SECONDS`     | `10`                     | Per-person broadcast suppression window.                                                 |
| `MAX_IMAGE_BYTES`      | `5242880`                | Hard cap for `/detect` payload size.                                                     |
| `ALLOWED_ORIGINS`      | `*`                      | Comma-separated CORS origins.                                                            |
| `LOG_LEVEL`            | `INFO`                   | stdlib logging level.                                                                    |
| `FACES_DIR`            | `data/faces`             | Reference photos directory scanned at startup.                                           |
| `FACE_MATCH_THRESHOLD` | `0.6`                    | Max face-distance to count as a match (lower = stricter).                                |
| `FACE_DETECT_MODEL`    | `hog`                    | dlib face detector: `hog` (CPU) or `cnn` (GPU build).                                    |
| `REQUIRE_KNOWN_FACES`  | `1`                      | If truthy, refuse to start with an empty roster. Set `0` for dev / CI without faces.     |
| `ALL_USERS_CSV`        | `data/processed/{week}/all_users.csv` | Precomputed metrics for live `/detect` (CSV lookup by email). |
| `LEADERBOARD_WS_URL`   | _(TV runtime)_           | Set on TV via `?ws=` query param or `window.LEADERBOARD_WS_URL` in generated HTML. |

## LAN testing with a real phone

**The phone page must be opened over HTTPS** (or `http://localhost` on the same device as the backend). On plain HTTP from a LAN IP — e.g. `http://192.168.x.x:8000/phone` — modern browsers strip `navigator.mediaDevices` and no JS workaround can fix it. The phone page will detect this and render an `HTTPS required` panel with the quick-fix command shown below.

- **Option A — tunnel (fastest)**:

  ```bash
  cloudflared tunnel --url http://localhost:8000
  # or:  ngrok http 8000
  ```

  Open the printed HTTPS URL on the phone.

- **Option B — locally trusted HTTPS cert**:

  ```bash
  brew install mkcert nss
  mkcert -install
  mkcert localhost 127.0.0.1 my-laptop.local
  uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000 \
    --ssl-certfile ./localhost+2.pem --ssl-keyfile ./localhost+2-key.pem
  ```

  Trust the mkcert root on the phone (iOS: install + enable in Settings → General → About → Certificate Trust Settings).

If you switch the backend to HTTPS, pass `?ws=wss://<host>/ws` on the TV leaderboard URL so the browser connects over secure WebSocket.

### Browser compatibility

The phone page handles nine distinct failure modes — see [`docs/face-detection.md#browser-compatibility`](../docs/face-detection.md#browser-compatibility) for the full table. Notable cases:

- **In-app browsers** (Instagram, FB, LinkedIn, WeChat, TikTok, …) cannot access the camera; the page detects them via UA and prompts the user to open in Safari/Chrome.
- **iOS Safari autoplay rejection** is handled by a one-time "Tap to start camera" gesture overlay (no buttons in the happy path).
- **Old browsers / WebViews** that only expose `navigator.getUserMedia` / `webkitGetUserMedia` / `mozGetUserMedia` are supported via a built-in polyfill.

## Endpoints

See [`docs/face-detection.md#technical-details`](../docs/face-detection.md#technical-details) for the full routes table, message schema, and sequence diagram.

## Deployment notes

- The backend is intentionally not deployed anywhere by this repo. The weekly GitHub Action only regenerates the static leaderboard; if you want the realtime layer live, host the backend separately (Render / Fly.io / Railway / a LAN box) and open the TV with `?ws=wss://your-host/ws`.
- State is in-memory; do not run more than one backend process behind a load balancer unless you swap in a shared store for cooldown + WS membership.

## Required GitHub Secrets

- `HUB_API_KEY` — used by the weekly pipeline/generator.
- `DAILY_ACTIVITY_API_KEY` — used by `src/analysis.py` to generate `all_users.csv` (not required for uvicorn).
- `CURSOR_STATE` — used by workflow session restore.
- `EXTERNAL_API_SECRET` — required only if CI will run `download_faces.py`.
