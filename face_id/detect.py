"""
face_id/detect.py
-----------------
Detects the largest face in an image and returns its 128-dimensional encoding
along with the bounding box and a base64-encoded crop of the face region.

Dependencies: face_recognition, Pillow, numpy
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import face_recognition
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class FaceResult:
    """Container for a single detected face."""

    encoding: list[float]                  # 128-d vector
    bounding_box: dict[str, int]           # top, right, bottom, left
    face_crop_b64: str                     # base64-encoded JPEG of the face crop
    image_path: str                        # original image path
    num_faces_in_image: int = 1
    error: Optional[str] = field(default=None)

    def to_dict(self) -> dict:
        return {
            "image_path": self.image_path,
            "num_faces_in_image": self.num_faces_in_image,
            "bounding_box": self.bounding_box,
            "encoding_dim": len(self.encoding),
            "encoding_preview": self.encoding[:8],   # first 8 values for readability
            "face_crop_b64": self.face_crop_b64,
            "error": self.error,
        }


def _crop_face(image: np.ndarray, location: tuple[int, int, int, int]) -> str:
    """Crop the face region and return as base64-encoded JPEG string."""
    top, right, bottom, left = location
    # Add a small padding (10 %) around the detected box
    h, w = image.shape[:2]
    pad_y = int((bottom - top) * 0.10)
    pad_x = int((right - left) * 0.10)
    top    = max(0, top    - pad_y)
    bottom = min(h, bottom + pad_y)
    left   = max(0, left   - pad_x)
    right  = min(w, right  + pad_x)

    crop = image[top:bottom, left:right]
    pil_img = Image.fromarray(crop)
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def detect_and_encode(image_path: str | Path, model: str = "hog") -> FaceResult:
    """
    Detect the largest face in *image_path* and return a FaceResult.

    Parameters
    ----------
    image_path : str | Path
        Path to the input image (JPEG, PNG, BMP, etc.).
    model : str
        face_recognition detection model -- 'hog' (CPU-fast) or
        'cnn' (GPU-accurate, requires dlib built with CUDA).

    Returns
    -------
    FaceResult
        Always returns a FaceResult; check .error for failure details.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    logger.info("Loading image: %s", image_path)
    image = face_recognition.load_image_file(str(image_path))

    logger.info("Running face detection (model=%s)...", model)
    locations = face_recognition.face_locations(image, model=model)

    if not locations:
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=0,
            error="No face detected in the image.",
        )

    # Pick the largest face by bounding-box area
    def _area(loc: tuple) -> int:
        top, right, bottom, left = loc
        return (bottom - top) * (right - left)

    largest_location = max(locations, key=_area)
    top, right, bottom, left = largest_location

    logger.info("Found %d face(s). Encoding the largest...", len(locations))
    encodings = face_recognition.face_encodings(image, known_face_locations=[largest_location])

    if not encodings:
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=len(locations),
            error="Face detected but encoding failed (possibly too small or blurry).",
        )

    encoding_vec = encodings[0].tolist()
    crop_b64 = _crop_face(image, largest_location)

    result = FaceResult(
        encoding=encoding_vec,
        bounding_box={"top": top, "right": right, "bottom": bottom, "left": left},
        face_crop_b64=crop_b64,
        image_path=str(image_path),
        num_faces_in_image=len(locations),
    )

    logger.info(
        "Encoding done. BBox=(top=%d, right=%d, bottom=%d, left=%d)",
        top, right, bottom, left,
    )
    return result


# ---------------------------------------------------------------------------
# Quick smoke-test -- run this file directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    path = sys.argv[1] if len(sys.argv) > 1 else "samples/sample_face.jpg"
    result = detect_and_encode(path)
    print(json.dumps(result.to_dict(), indent=2))
