"""
FastAPI backend for the face-detection → TV display pipeline.

Routes
------
- POST  /detect    Phone uploads a frame (multipart or base64 JSON). The
                   image is fed to the recognition seam; on a fresh
                   identification, a PERSON_DETECTED event is broadcast
                   over the /ws WebSocket. Same person is suppressed
                   within COOLDOWN_SECONDS to avoid flooding the TV.
- WS    /ws        TVs connect here to receive PERSON_DETECTED events.
- GET   /phone     Serves frontend/phone.html so the phone can hit a
                   single host for both the page and the API (avoids
                   CORS gymnastics on the camera side).
- GET   /health    Liveness probe; also exposes current connection count.
- GET   /faces/{filename}  Serves reference photos for the TV overlay.

Design notes
------------
- State is in-memory only (per the spec). Cooldown and WS connections
  live in the process. A Redis-backed swap is intentionally out of
  scope for v1 but the ConnectionManager interface won't change.
- All handlers are async.
- CORS is wide-open in v1 (no auth requirement). Tighten via
  ALLOWED_ORIGINS in production.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, TypedDict

from activity_client import Metrics, fetch_daily_metrics, preload_metrics_index
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import mimetypes
from recognition import KnownFaces, MatchResult, load_known_faces, recognize_face

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pathlib import Path
import mimetypes

# 🔧 Configurable settings
BASE_DIRS = [
    Path(".").resolve(),                       # project root
    Path("./output").resolve(),                # generated files
    Path("./assets").resolve(),                # static assets
]

# ─── Configuration ───────────────────────────────────────────────────────────

COOLDOWN_SECONDS: float = float(os.getenv("COOLDOWN_SECONDS", "10"))
MAX_IMAGE_BYTES: int = int(os.getenv("MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

# Phone HTML is served from this backend so the phone has a single
# trustworthy origin for camera permission + API calls.
REPO_ROOT = Path(__file__).resolve().parent.parent
PHONE_HTML_PATH = REPO_ROOT / "frontend" / "phone.html"

# Real face-recognition config. Encodings are loaded once in the
# lifespan; the route only reads from the cache.
FACES_DIR = Path(os.getenv("FACES_DIR", str(REPO_ROOT / "data" / "faces")))
FACE_MATCH_THRESHOLD: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.45"))
FACE_DETECT_MODEL: str = os.getenv("FACE_DETECT_MODEL", "hog")
REQUIRE_KNOWN_FACES: bool = os.getenv("REQUIRE_KNOWN_FACES", "1") not in (
    "0", "false", "False", "no", "",
)
class DetectionPayload(TypedDict):
    name: str
    email: str
    image: str
    metrics: Metrics

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("face_backend")


# ─── WebSocket connection manager ────────────────────────────────────────────


class ConnectionManager:
    """Tracks active TV WebSocket connections and fans out events.

    A dead/slow connection on broadcast should never block or kill
    delivery to other TVs — failures are logged and the offending
    socket is removed.
    """

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._active.add(websocket)
        logger.info("ws connect total=%d", len(self._active))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active.discard(websocket)
        logger.info("ws disconnect total=%d", len(self._active))

    @property
    def connection_count(self) -> int:
        return len(self._active)

    async def broadcast(self, payload: dict) -> int:
        """Send `payload` as JSON to every active connection.

        Returns the number of successful sends. Failed sockets are
        removed so a stale TV doesn't keep failing on every event.
        """

        async with self._lock:
            targets = list(self._active)

        if not targets:
            return 0

        async def _send(ws: WebSocket) -> bool:
            try:
                await ws.send_json(payload)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws send failed, dropping connection: %s", exc)
                async with self._lock:
                    self._active.discard(ws)
                return False

        results = await asyncio.gather(*(_send(ws) for ws in targets))
        delivered = sum(1 for ok in results if ok)
        logger.info("broadcast delivered=%d/%d", delivered, len(targets))
        return delivered


# ─── Cooldown ────────────────────────────────────────────────────────────────


class Cooldown:
    """Per-person broadcast cooldown.

    `should_broadcast(person_id)` returns True only if `person_id` has not
    been broadcast within the last `window_seconds`. The check + mark is
    atomic under an asyncio.Lock so two concurrent detections of the same
    person can't both pass through.
    """

    def __init__(self, window_seconds: float) -> None:
        self._window = window_seconds
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def should_broadcast(self, person_id: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            last = self._last.get(person_id, 0.0)
            if now - last < self._window:
                return False
            self._last[person_id] = now
            return True


# ─── App lifespan ────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.connections = ConnectionManager()
    app.state.cooldown = Cooldown(COOLDOWN_SECONDS)

    # Encode known faces exactly once. CPU-bound; the lifespan runs
    # before uvicorn starts accepting requests, so blocking here is
    # acceptable and keeps the per-request path lock-free.
    logger.info("loading known faces from %s", FACES_DIR)
    known: KnownFaces = await asyncio.to_thread(load_known_faces, FACES_DIR)
    app.state.known_faces = known

    if not known and REQUIRE_KNOWN_FACES:
        raise RuntimeError(
            f"No usable known faces in {FACES_DIR}. "
            "Add reference photos named '<name>_<email>.jpg' or set "
            "REQUIRE_KNOWN_FACES=0 to allow startup with an empty roster."
        )

    metrics_csv = await asyncio.to_thread(preload_metrics_index)
    logger.info(
        "backend up cooldown=%.1fs max_image_bytes=%d allowed_origins=%s "
        "known_faces=%d threshold=%.2f model=%s metrics_csv=%s",
        COOLDOWN_SECONDS,
        MAX_IMAGE_BYTES,
        ALLOWED_ORIGINS,
        len(known),
        FACE_MATCH_THRESHOLD,
        FACE_DETECT_MODEL,
        metrics_csv,
    )
    yield
    logger.info("backend shutting down")


app = FastAPI(title="Face Detection TV Pipeline", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _extract_image_bytes(request: Request, image: Optional[UploadFile]) -> bytes:
    """Pull image bytes from either multipart upload or JSON base64 payload.

    Raises HTTPException(400) on validation problems.
    """

    content_type = (request.headers.get("content-type") or "").lower()

    if image is not None:
        data = await image.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty image upload")
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image too large (>{MAX_IMAGE_BYTES} bytes)",
            )
        return data

    if "application/json" in content_type:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

        b64 = body.get("image_b64") if isinstance(body, dict) else None
        if not isinstance(b64, str) or not b64:
            raise HTTPException(
                status_code=400,
                detail="Missing 'image_b64' string in JSON body",
            )

        # Tolerate data URLs like "data:image/jpeg;base64,...."
        if "," in b64 and b64.lstrip().startswith("data:"):
            b64 = b64.split(",", 1)[1]

        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid base64 image") from exc

        if not data:
            raise HTTPException(status_code=400, detail="Empty image payload")
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image too large (>{MAX_IMAGE_BYTES} bytes)",
            )
        return data

    raise HTTPException(
        status_code=400,
        detail=(
            "Expected multipart/form-data with an 'image' file "
            "or application/json with 'image_b64'"
        ),
    )


# ─── Routes ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> JSONResponse:
    manager: ConnectionManager = app.state.connections
    return JSONResponse({"ok": True, "connections": manager.connection_count})


@app.get("/phone")
async def phone_page() -> FileResponse:
    if not PHONE_HTML_PATH.exists():
        raise HTTPException(status_code=500, detail="phone.html is not deployed")
    # no-store: developers iterating on phone.html shouldn't need a hard refresh.
    return FileResponse(
        PHONE_HTML_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def _safe_face_path(filename: str) -> Path:
    """Resolve a basename-only path under FACES_DIR or raise 404."""

    safe_name = Path(filename).name
    if not safe_name or safe_name != filename.strip():
        raise HTTPException(status_code=400, detail="Invalid filename")
    candidate = FACES_DIR / safe_name
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Face image not found")
    try:
        candidate.resolve().relative_to(FACES_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Face image not found") from exc
    return candidate


@app.get("/faces/{filename}")
async def serve_face(filename: str) -> FileResponse:
    """Serve a reference face image for the TV live overlay."""

    path = _safe_face_path(filename)
    media = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=3600"})


DEFAULT_ALLOWED_EXTENSIONS = {
    ".html", ".css", ".js",
    ".jpg", ".jpeg", ".png", ".webp",
    ".svg", ".gif",
    ".mp4"
}

@app.get("/{file_path:path}")
async def serve_file(
    file_path: str,
    cache: bool = Query(True, description="Enable browser cache"),
):
    """
    Dynamically serve any file from allowed directories.
    """

    requested_path = Path(file_path)

    # 🔍 Find file in allowed base directories
    resolved_file = None
    for base_dir in BASE_DIRS:
        candidate = (base_dir / requested_path).resolve()
        if candidate.exists() and candidate.is_file():
            resolved_file = candidate
            break

    if not resolved_file:
        raise HTTPException(status_code=404, detail="File not found")

    # 🔐 Security: ensure file is inside allowed dirs
    if not any(str(resolved_file).startswith(str(base)) for base in BASE_DIRS):
        raise HTTPException(status_code=403, detail="Access denied")

    # 📎 Extension check
    if resolved_file.suffix.lower() not in DEFAULT_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")

    # 🧠 MIME type
    mime_type, _ = mimetypes.guess_type(resolved_file)
    mime_type = mime_type or "application/octet-stream"

    headers = {
        "Cache-Control": "public, max-age=3600" if cache else "no-cache, no-store"
    }

    return FileResponse(
        resolved_file,
        media_type=mime_type,
        headers=headers
    )

@app.post("/detect")
async def detect(
    request: Request,
    image: Optional[UploadFile] = File(default=None),
) -> JSONResponse:
    """Receive a frame, identify the person, broadcast on cooldown miss."""

    image_bytes = await _extract_image_bytes(request, image)
    manager: ConnectionManager = app.state.connections

    known: KnownFaces = app.state.known_faces
    # Recognition is CPU-bound (dlib). Offload so the event loop stays
    # responsive to concurrent requests / WS pings.
    match: Optional[MatchResult] = await asyncio.to_thread(
        recognize_face,
        image_bytes,
        known,
        threshold=FACE_MATCH_THRESHOLD,
        model=FACE_DETECT_MODEL,
    )
    if match is None:
        print("no face")
        return JSONResponse({"status": "no_face", "person": None})

    if match is not None and match["matched"] == False:
        await manager.broadcast({"type": "PERSON_DETECTED", "payload": {"id":"123", "name": "Unknown", "email": "unknown", "image": "unknown", "metrics": None}, "employee_found": False, "data_found": False})
        return JSONResponse({"status": "no_match", "person": None})

    metrics: Optional[Metrics] = await asyncio.to_thread(
        fetch_daily_metrics, match["email"]
    )
    payload: DetectionPayload = {
        "name": match["name"],
        "email": match["email"],
        "image": match["image_filename"],
        "metrics": metrics,
    }
    if metrics is None:
        print("metrics not found")
        await manager.broadcast({"type": "PERSON_DETECTED", "payload": payload, "employee_found": True, "data_found": False})
        # No CSV row for this email — do not broadcast or expose person data.
        return JSONResponse({"status": "metrics_not_found", "person": None})


    cooldown: Cooldown = app.state.cooldown
    if not await cooldown.should_broadcast(payload["email"]):
        logger.info(
            "cooldown hit email=%s name=%s confidence=%.3f",
            payload["email"],
            payload["name"],
            match["confidence"],
        )
        return JSONResponse({"status": "cooldown", "person": payload})

    await manager.broadcast({"type": "PERSON_DETECTED", "payload": payload, "data": True})
    logger.info(
        "detected email=%s name=%s confidence=%.3f active_days=%s",
        payload["email"],
        payload["name"],
        match["confidence"],
        payload["metrics"]["activeDays"],
    )

    return JSONResponse({"status": "face_detected", "person": payload})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """TV WebSocket endpoint. Receives PERSON_DETECTED events as JSON."""

    manager: ConnectionManager = app.state.connections
    await manager.connect(websocket)
    try:
        # Hello on connect helps verify wiring in DevTools.
        await websocket.send_json({"type": "HELLO"})
        # Keep the socket open. We don't expect inbound messages from TVs,
        # but draining receive() ensures pings/pongs and clean disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws unexpected error: %s", exc)
    finally:
        await manager.disconnect(websocket)
