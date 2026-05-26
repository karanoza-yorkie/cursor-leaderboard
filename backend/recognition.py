"""
Real face recognition backed by the `face_recognition` library (dlib).

Loads reference photos from a directory once at process startup, encodes
each known face to a 128-dim vector, and exposes a synchronous
``recognize_face`` that takes raw image bytes and returns the best
matching identity (or ``None``).

Design rules (enforced; mirror the plan):

- This module imports **no** FastAPI / Starlette code. It is a pure
  recognition seam. The FastAPI route is responsible for offloading the
  CPU-bound call via ``asyncio.to_thread`` so the event loop is never
  blocked.
- Encodings are computed exactly once (at startup) and held in memory
  in a numpy stack for vectorised distance computation.
- The recognition function is read-only against the cache and therefore
  safe to call concurrently from multiple worker threads.
- Match logic uses both ``face_distance`` (to pick the best candidate)
  and ``compare_faces`` (to gate the threshold), exactly as the spec
  describes. Confidence is derived directly from the library's
  distance, no invented curve: ``confidence = 1.0 - distance`` clamped
  to ``[0, 1]`` and rounded to 3 decimals.

Filename convention for known-face images
-----------------------------------------
``<name>_<id>.<ext>``, where ``<ext>`` is one of ``jpg``, ``jpeg``,
``png``. ``<name>`` may contain ASCII letters, digits, ``.`` or ``-``;
``<id>`` is alphanumeric. Example: ``nilesh_YI141.jpg`` →
``name="Nilesh"``, ``id="YI141"``. Files that don't match the pattern
are skipped with a warning.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional, TypedDict

import face_recognition  # dlib-backed
import numpy as np
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


# ─── Types ───────────────────────────────────────────────────────────────────


class Person(TypedDict):
    """Shape of the WS broadcast payload, assembled by the route.

    The recognizer itself only knows id / name / confidence; department
    and message are mocked in the route per the spec.
    """

    id: str
    name: str
    department: str
    message: str


class MatchResult(TypedDict):
    """Return type of `recognize_face`."""

    id: str
    name: str
    confidence: float


@dataclass(frozen=True)
class KnownFace:
    """One reference identity. Encoding is a 128-dim float32 vector."""

    id: str
    name: str
    encoding: np.ndarray  # shape (128,)


class KnownFaces:
    """In-memory cache of known identities.

    ``encodings`` is a stacked ``(N, 128)`` array so ``face_distance``
    is one vectorised call per probe. Treated as read-only after load.
    """

    __slots__ = ("faces", "encodings")

    def __init__(self, faces: list[KnownFace]) -> None:
        self.faces: list[KnownFace] = list(faces)
        if self.faces:
            self.encodings: np.ndarray = np.stack([f.encoding for f in self.faces])
        else:
            self.encodings = np.zeros((0, 128), dtype=np.float64)

    def __len__(self) -> int:
        return len(self.faces)

    def __bool__(self) -> bool:
        return bool(self.faces)


# ─── Filename parsing ────────────────────────────────────────────────────────


_FILENAME_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9.\-]*)_(?P<id>[A-Za-z0-9]+)$"
)
_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _parse_filename(stem: str) -> Optional[tuple[str, str]]:
    """Return ``(display_name, id)`` for a valid stem, else ``None``."""

    m = _FILENAME_RE.match(stem)
    if not m:
        return None
    raw_name = m.group("name")
    face_id = m.group("id")
    # Title-case for human display: "nilesh" -> "Nilesh", "ali-baba" -> "Ali-Baba".
    display = "-".join(part.capitalize() for part in raw_name.split("-"))
    return display, face_id


# ─── Image decoding ──────────────────────────────────────────────────────────


def _decode_image_to_rgb(image_bytes: bytes) -> Optional[np.ndarray]:
    """Decode JPEG/PNG/etc. bytes into a contiguous RGB uint8 numpy array.

    Returns ``None`` for corrupt / non-image payloads. The route has
    already validated size limits before calling us.
    """

    if not image_bytes:
        return None
    try:
        with Image.open(BytesIO(image_bytes)) as im:
            rgb = im.convert("RGB")
            arr = np.array(rgb, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("Failed to decode probe image: %s", exc)
        return None
    # face_recognition / dlib want a contiguous array.
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr


# ─── Startup loader ──────────────────────────────────────────────────────────


def load_known_faces(directory: Path) -> KnownFaces:
    """Scan ``directory`` for reference photos and encode each one.

    Behaviour (per plan):

    - Missing directory → returns an empty ``KnownFaces`` (the route /
      lifespan decides whether that's fatal via ``REQUIRE_KNOWN_FACES``).
    - File whose stem doesn't match ``<name>_<id>`` → skipped with a
      warning.
    - File with no detectable face → skipped with a warning.
    - File with multiple detectable faces → first encoding is used and
      a warning is emitted (reference photos should be single-face).
    """

    directory = Path(directory)
    if not directory.exists():
        logger.warning("Known-faces directory does not exist: %s", directory)
        return KnownFaces([])

    if not directory.is_dir():
        logger.warning("Known-faces path is not a directory: %s", directory)
        return KnownFaces([])

    files = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _ALLOWED_SUFFIXES
    )

    loaded: list[KnownFace] = []
    skipped = 0
    for path in files:
        parsed = _parse_filename(path.stem)
        if parsed is None:
            logger.warning(
                "Skipping %s: filename does not match '<name>_<id>.<ext>'", path.name
            )
            skipped += 1
            continue
        display_name, face_id = parsed

        try:
            image = face_recognition.load_image_file(str(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: could not read image (%s)", path.name, exc)
            skipped += 1
            continue

        try:
            encodings = face_recognition.face_encodings(image)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: encoding failed (%s)", path.name, exc)
            skipped += 1
            continue

        if not encodings:
            logger.warning("Skipping %s: no face detected", path.name)
            skipped += 1
            continue
        if len(encodings) > 1:
            logger.warning(
                "%s contains %d faces; using the first. Reference photos should be single-face.",
                path.name, len(encodings),
            )

        loaded.append(
            KnownFace(id=face_id, name=display_name, encoding=encodings[0])
        )
        logger.info("Loaded known face id=%s name=%s from %s",
                    face_id, display_name, path.name)

    logger.info("Known-face load complete: loaded=%d skipped=%d from %s",
                len(loaded), skipped, directory)
    return KnownFaces(loaded)


# ─── Recognition ─────────────────────────────────────────────────────────────


# face_recognition's `compare_faces` calls `face_distance` internally;
# we keep both calls because the spec explicitly listed them, and the
# `compare_faces` call documents intent at the call site.
def recognize_face(
    image_bytes: bytes,
    known: KnownFaces,
    *,
    threshold: float = 0.6,
    model: str = "hog",
) -> Optional[MatchResult]:
    """Identify the best-matching known face in ``image_bytes``.

    Returns ``None`` when:
      - the cache is empty,
      - the image fails to decode,
      - no face is detected,
      - the best candidate's distance exceeds ``threshold``.

    Otherwise returns ``{id, name, confidence}`` where
    ``confidence = round(max(0, min(1, 1 - distance)), 3)``.

    Synchronous and CPU-bound; callers in async contexts should wrap
    this with ``asyncio.to_thread``.
    """

    if not known:
        return None

    image = _decode_image_to_rgb(image_bytes)
    if image is None:
        return None

    # 1) Locate faces. HOG is the default (CPU); CNN requires a GPU build.
    locations = face_recognition.face_locations(image, model=model)
    if not locations:
        return None

    # 2) Encode the first face only (per spec).
    encodings = face_recognition.face_encodings(
        image, known_face_locations=locations[:1]
    )
    if not encodings:
        return None
    probe = encodings[0]

    # 3) Distance to every known encoding (vectorised over the stack).
    distances = face_recognition.face_distance(known.encodings, probe)
    if distances.size == 0:
        return None

    # 4) Threshold gate via compare_faces, then best-by-distance.
    matches = face_recognition.compare_faces(
        list(known.encodings), probe, tolerance=threshold
    )
    best_idx = int(np.argmin(distances))
    if not matches[best_idx]:
        return None

    distance = float(distances[best_idx])
    confidence = round(max(0.0, min(1.0, 1.0 - distance)), 3)

    match = known.faces[best_idx]
    logger.debug(
        "Recognized id=%s name=%s distance=%.3f confidence=%.3f",
        match.id, match.name, distance, confidence,
    )
    return {"id": match.id, "name": match.name, "confidence": confidence}
