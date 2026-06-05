# API Reference

HTTP and WebSocket API for the FastAPI realtime backend (`backend/main.py`).

**Base URL (local):** `http://localhost:8000`  
**Server:** `uvicorn main:app --app-dir backend`

There is **no authentication** on these endpoints in v1. Restrict access via network policy, reverse proxy, or `ALLOWED_ORIGINS` in production.

---

## REST Endpoints

### `GET /health`

Liveness probe.

**Response** `200 application/json`:

```json
{
  "ok": true,
  "connections": 0
}
```

`connections` is the count of active TV WebSocket clients.

---

### `GET /phone`

Serves the camera capture page (`frontend/phone.html`) from the same origin as the API.

**Response:** `200 text/html`  
**Headers:** `Cache-Control: no-store`

---

### `POST /detect`

Receive a camera frame, run face recognition, optionally broadcast to TVs.

#### Request formats

**Option A — multipart form**

```
Content-Type: multipart/form-data

image: <binary file>
```

**Option B — JSON**

```
Content-Type: application/json

{
  "image_b64": "<base64 string or data:image/jpeg;base64,...>"
}
```

**Limits:** Max payload size = `MAX_IMAGE_BYTES` (default 5 MB).

#### Response `200 application/json`

| `status` | Meaning |
|----------|---------|
| `face_detected` | Match found, metrics loaded, broadcast sent (or cooldown already passed) |
| `cooldown` | Same person detected within cooldown window; no broadcast |
| `no_face` | No face in image |
| `no_match` | Face detected but not in known roster |
| `metrics_not_found` | Match found but email absent from `all_users.csv`; no broadcast |

**Example — success:**

```json
{
  "status": "face_detected",
  "person": {
    "name": "Nilesh Sukhwani",
    "email": "nileshs@york.ie",
    "image": "nilesh-sukhwani_nileshs@york.ie.png",
    "metrics": {
      "totalAiLines": 573,
      "promptCount": 29,
      "avgScore": 5.86,
      "activeDays": 4,
      "usageScore": 72.5,
      "finalScore": 68.3,
      "rank": 3
    }
  }
}
```

**Example — cooldown:**

```json
{
  "status": "cooldown",
  "person": { "...": "..." }
}
```

#### Error responses

| Code | Cause |
|------|-------|
| `400` | Empty image, invalid base64, missing field, oversized payload |
| `500` | Internal error |

---

### `GET /faces/{filename}`

Serve a reference face image for the TV overlay.

- **Path param:** basename only (e.g. `nilesh-sukhwani_nileshs@york.ie.png`)
- **Response:** `200 image/jpeg` or `image/png`
- **Headers:** `Cache-Control: public, max-age=3600`
- **Errors:** `400` invalid filename, `404` not found

---

### `GET /{file_path:path}`

Static file server for allowed directories (`repo root`, `output/`, `assets/`).

**Allowed extensions:** `.html`, `.css`, `.js`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.svg`, `.gif`, `.mp4`

**Query params:**

| Param | Default | Purpose |
|-------|---------|---------|
| `cache` | `true` | Set `false` for `no-cache, no-store` |

**Errors:** `403` disallowed type or path, `404` not found

---

## WebSocket: `/ws`

TV browsers connect here to receive live detection events.

### Connection

```
ws://localhost:8000/ws
wss://your-host/ws   # required from HTTPS pages (GitHub Pages)
```

### Server → client messages

**On connect:**

```json
{ "type": "HELLO" }
```

**On detection (broadcast):**

```json
{
  "type": "PERSON_DETECTED",
  "payload": {
    "name": "Nilesh Sukhwani",
    "email": "nileshs@york.ie",
    "image": "nilesh-sukhwani_nileshs@york.ie.png",
    "metrics": {
      "totalAiLines": 573,
      "promptCount": 29,
      "avgScore": 5.86,
      "activeDays": 4,
      "usageScore": 72.5,
      "finalScore": 68.3,
      "rank": 3
    }
  },
  "employee_found": true,
  "data_found": true
}
```

**Unknown person variant:**

```json
{
  "type": "PERSON_DETECTED",
  "payload": {
    "id": "123",
    "name": "Unknown",
    "email": "unknown",
    "image": "unknown",
    "metrics": null
  },
  "employee_found": false,
  "data_found": false
}
```

**Metrics missing variant:**

```json
{
  "type": "PERSON_DETECTED",
  "payload": { "name": "...", "email": "...", "image": "...", "metrics": null },
  "employee_found": true,
  "data_found": false
}
```

### Client → server

No messages required. The server drains `receive_text()` to detect disconnects. TVs are receive-only.

### Reconnection (TV client)

The generated leaderboard uses exponential backoff: 1s initial, doubling to 30s max, reset on successful `onopen`.

---

## Metrics Payload Fields

Mapped from `all_users.csv` by `backend/activity_client.py`:

| Field | CSV column(s) |
|-------|---------------|
| `totalAiLines` | `Total_AI_Lines` |
| `promptCount` | `Total_Prompts` or `total_prompts` |
| `avgScore` | `quality_score` |
| `activeDays` | `Active_Days` |
| `usageScore` | `usage_score` |
| `finalScore` | `final_score` |
| `rank` | Computed at load (sort by `final_score` desc) |

Override CSV path with `ALL_USERS_CSV` environment variable.

---

## Face Recognition

Configured via environment (see [configuration.md](./configuration.md)):

| Setting | Default | Purpose |
|---------|---------|---------|
| `FACES_DIR` | `data/faces` | Reference photo directory |
| `FACE_MATCH_THRESHOLD` | `0.45` | Max L2 distance for match |
| `FACE_DETECT_MODEL` | `hog` | CPU face detector |

**Filename convention:** `{name-segment}_{email}.{jpg|jpeg|png}`  
Example: `nilesh-sukhwani_nileshs@york.ie.png`

Implementation: `backend/recognition.py` using the `face_recognition` library (dlib).

---

## Example: End-to-End cURL Test

```bash
# 1. Health
curl -s http://localhost:8000/health | jq

# 2. Detect with a known face photo
curl -s -X POST http://localhost:8000/detect \
  -F "image=@data/faces/nilesh-sukhwani_nileshs@york.ie.png" | jq

# 3. WebSocket (requires wscat: npm i -g wscat)
wscat -c ws://localhost:8000/ws
# Then POST /detect in another terminal; wscat receives PERSON_DETECTED
```

---

## Related

- [face-detection.md](./face-detection.md) — overlay behavior, browser compatibility
- [backend/README.md](../backend/README.md) — HTTPS setup for phone camera
- [architecture.md](./architecture.md) — system context
