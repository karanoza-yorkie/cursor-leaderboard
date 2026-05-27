"""
Real face recognition backed by the `face_recognition` library (dlib).

Loads reference photos from a directory once at process startup, encodes
each known face to a 128-dim vector, and exposes a synchronous
``recognize_face`` that takes raw image bytes and returns the best
matching identity (or ``None``).

Filename convention for known-face images
-----------------------------------------
``<name>_<email>.<ext>``, where ``<ext>`` is one of ``jpg``, ``jpeg``,
``png``. Everything after the first ``_`` is the email (must contain
``@``). Example: ``nilesh_nileshs@york.ie.jpg`` →
``name="Nilesh"``, ``email="nileshs@york.ie"``.
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


class MatchResult(TypedDict):
    """Return type of `recognize_face`."""

    name: str
    email: str
    image_filename: str
    confidence: float


@dataclass(frozen=True)
class KnownFace:
    """One reference identity. Encoding is a 128-dim float32 vector."""

    email: str
    name: str
    image_filename: str
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


_NAME_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]*$")
_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _parse_filename(stem: str) -> Optional[tuple[str, str]]:
    """Return ``(display_name, email)`` for a valid stem, else ``None``."""

    if "_" not in stem:
        return None
    raw_name, email = stem.split("_", 1)
    print(raw_name, email)
    if not raw_name or not email or "@" not in email:
        return None
    if ".." in email or "/" in email or "\\" in email:
        return None
    if not _NAME_PREFIX_RE.match(raw_name):
        return None
    print(raw_name, email)
    display = "-".join(part.capitalize() for part in raw_name.split("-"))
    return display.replace("-", " "), email.lower()


# ─── Image decoding ──────────────────────────────────────────────────────────


def _decode_image_to_rgb(image_bytes: bytes) -> Optional[np.ndarray]:
    """Decode JPEG/PNG/etc. bytes into a contiguous RGB uint8 numpy array."""

    if not image_bytes:
        return None
    try:
        with Image.open(BytesIO(image_bytes)) as im:
            rgb = im.convert("RGB")
            arr = np.array(rgb, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("Failed to decode probe image: %s", exc)
        return None
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr


# ─── Startup loader ──────────────────────────────────────────────────────────


def load_known_faces(directory: Path) -> KnownFaces:
    """Scan ``directory`` for reference photos and encode each one."""

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
                "Skipping %s: filename does not match '<name>_<email>.<ext>'",
                path.name,
            )
            skipped += 1
            continue
        display_name, email = parsed

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
                "%s contains %d faces; using the first.",
                path.name,
                len(encodings),
            )

        loaded.append(
            KnownFace(
                email=email,
                name=display_name,
                image_filename=path.name,
                encoding=encodings[0],
            )
        )
        logger.info(
            "Loaded known face email=%s name=%s from %s",
            email,
            display_name,
            path.name,
        )

    logger.info(
        "Known-face load complete: loaded=%d skipped=%d from %s",
        len(loaded),
        skipped,
        directory,
    )
    return KnownFaces(loaded)


# ─── Recognition ─────────────────────────────────────────────────────────────


def recognize_face(
    image_bytes: bytes,
    known: KnownFaces,
    *,
    threshold: float = 0.6,
    model: str = "hog",
) -> Optional[MatchResult]:
    """Identify the best-matching known face in ``image_bytes``."""

    if not known:
        return None

    image = _decode_image_to_rgb(image_bytes)
    if image is None:
        return None

    locations = face_recognition.face_locations(image, model=model)
    if not locations:
        return None

    encodings = face_recognition.face_encodings(
        image, known_face_locations=locations[:1]
    )
    if not encodings:
        return None
    probe = encodings[0]

    distances = face_recognition.face_distance(known.encodings, probe)
    if distances.size == 0:
        return None

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
        "Recognized email=%s name=%s distance=%.3f confidence=%.3f",
        match.email,
        match.name,
        distance,
        confidence,
    )
    return {
        "name": match.name,
        "email": match.email,
        "image_filename": match.image_filename,
        "confidence": confidence,
    }
