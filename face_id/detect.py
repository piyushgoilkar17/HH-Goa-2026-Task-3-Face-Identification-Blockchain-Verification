"""
face_id/detect.py
-----------------
Detects the largest face in an image and returns its 128-dimensional encoding
along with the bounding box and a base64-encoded crop of the face region.

Dependencies: deepface, opencv-python, Pillow, numpy
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

try:
    from deepface import DeepFace
except ImportError:
    DeepFace = None

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


def _crop_face(image_array: np.ndarray, location: dict[str, int]) -> str:
    """Crop the face region and return as base64-encoded JPEG string."""
    top = location["top"]
    right = location["right"]
    bottom = location["bottom"]
    left = location["left"]
    
    # Add a small padding (10 %) around the detected box
    h, w = image_array.shape[:2]
    pad_y = int((bottom - top) * 0.10)
    pad_x = int((right - left) * 0.10)
    top    = max(0, top    - pad_y)
    bottom = min(h, bottom + pad_y)
    left   = max(0, left   - pad_x)
    right  = min(w, right  + pad_x)

    crop = image_array[top:bottom, left:right]
    pil_img = Image.fromarray(crop)
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def detect_and_encode(image_path: str | Path, model: str = "Facenet") -> FaceResult:
    """
    Detect the largest face in *image_path* and return a FaceResult.

    Parameters
    ----------
    image_path : str | Path
        Path to the input image (JPEG, PNG, BMP, etc.).
    model : str
        DeepFace model name. Defaults to "Facenet" which produces 128-d embeddings.

    Returns
    -------
    FaceResult
        Always returns a FaceResult; check .error for failure details.
    """
    if DeepFace is None:
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=0,
            error="DeepFace is not installed. Run `pip install deepface`.",
        )

    image_path = Path(image_path)
    if not image_path.exists():
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=0,
            error=f"Image not found: {image_path}",
        )

    logger.info("Loading image and running face detection (model=%s)...", model)
    
    try:
        results = DeepFace.represent(img_path=str(image_path), model_name=model, enforce_detection=True, detector_backend="mtcnn")
    except ValueError as e:
        # DeepFace raises ValueError when no face is found if enforce_detection is True
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=0,
            error=str(e) if "could not be detected" in str(e).lower() else f"Detection error: {e}",
        )
    except Exception as e:
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=0,
            error=f"DeepFace processing error: {e}",
        )

    if not results:
        return FaceResult(
            encoding=[],
            bounding_box={},
            face_crop_b64="",
            image_path=str(image_path),
            num_faces_in_image=0,
            error="No face detected in the image.",
        )

    # Pick the largest face by bounding-box area
    def _area(res: dict) -> int:
        region = res.get("facial_area", {})
        return region.get("w", 0) * region.get("h", 0)

    largest_result = max(results, key=_area)
    region = largest_result["facial_area"]
    
    left = region["x"]
    top = region["y"]
    right = left + region["w"]
    bottom = top + region["h"]
    bounding_box = {"top": top, "right": right, "bottom": bottom, "left": left}
    
    encoding_vec = largest_result["embedding"]
    
    logger.info("Found %d face(s). Extracting crop for the largest...", len(results))
    
    # Load original image with PIL/numpy to crop accurately based on returned coordinates
    # (DeepFace uses OpenCV BGR usually, PIL uses RGB)
    orig_img = Image.open(image_path).convert("RGB")
    orig_np = np.array(orig_img)
    
    crop_b64 = _crop_face(orig_np, bounding_box)

    result = FaceResult(
        encoding=encoding_vec,
        bounding_box=bounding_box,
        face_crop_b64=crop_b64,
        image_path=str(image_path),
        num_faces_in_image=len(results),
    )

    logger.info(
        "Encoding done. BBox=(top=%d, right=%d, bottom=%d, left=%d)",
        top, right, bottom, left,
    )
    return result


if __name__ == "__main__":
    import sys, json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    path = sys.argv[1] if len(sys.argv) > 1 else "samples/sample_face.jpg"
    result = detect_and_encode(path)
    print(json.dumps(result.to_dict(), indent=2))
