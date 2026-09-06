"""
main.py
-------
Face-Verify-Chain pipeline entry point.

Pipeline:
    1. face_id.detect  -- detect + encode face from input image
    2. search.reverse_search -- reverse image search via SerpAPI
    3. Save results to match_record.json

Usage
-----
    python main.py <image_path> [--output match_record.json] [--max-results 5] [--model hog]

Example
-------
    python main.py samples/sample_face.jpg
    python main.py samples/sample_face.jpg --output results/my_run.json --max-results 10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must be before any module-level env reads

from face_id.detect import detect_and_encode
from search.reverse_search import reverse_search_by_b64

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def build_record(image_path: str, max_results: int, model: str) -> dict:
    """
    Run the full pipeline and return the record dict to be saved.
    """
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- Step 1: Face detection & encoding --------------------------------
    logger.info("=== STEP 1: Face Detection ===")
    face_result = detect_and_encode(image_path, model=model)

    if face_result.error:
        logger.error("Face detection failed: %s", face_result.error)
        return {
            "pipeline_status": "failed",
            "stage": "face_detection",
            "error": face_result.error,
            "image_path": image_path,
            "started_at": started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    logger.info(
        "Face detected: %d face(s) in image. Encoding dim=%d.",
        face_result.num_faces_in_image,
        len(face_result.encoding),
    )

    # ---- Step 2: Reverse image search -------------------------------------
    logger.info("=== STEP 2: Reverse Image Search ===")
    matches = []
    search_error = None

    try:
        matches = reverse_search_by_b64(
            face_result.face_crop_b64,
            max_results=max_results,
        )
    except RuntimeError as exc:
        search_error = str(exc)
        logger.error("Reverse search failed: %s", search_error)
    except Exception as exc:
        search_error = f"Unexpected error: {exc}"
        logger.exception("Reverse search raised an unexpected exception.")

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- Step 3: Assemble record ------------------------------------------
    record = {
        "pipeline_status": "success" if not search_error else "partial",
        "image_path": image_path,
        "started_at": started_at,
        "finished_at": finished_at,

        # Face detection outputs
        "face_detection": {
            "num_faces_in_image": face_result.num_faces_in_image,
            "bounding_box": face_result.bounding_box,
            "encoding_dim": len(face_result.encoding),
            # Full 128-d encoding stored for downstream use
            "encoding": face_result.encoding,
            # Crop stored as base64 so the JSON is self-contained
            "face_crop_b64": face_result.face_crop_b64,
        },

        # Reverse search outputs
        "reverse_search": {
            "search_error": search_error,
            "num_matches": len(matches),
            "matches": [m.to_dict() for m in matches],
        },

        # Convenience: top result at root level for quick access
        "top_match": matches[0].to_dict() if matches else None,
    }

    return record


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------

def save_record(record: dict, output_path: str | Path) -> Path:
    """
    Append the new record to a JSON array in *output_path*.
    Creates the file if it does not exist; appends if it does.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing records (if any)
    existing: list[dict] = []
    if output_path.exists() and output_path.stat().st_size > 0:
        try:
            with output_path.open("r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = [existing]
        except json.JSONDecodeError:
            logger.warning("Existing %s could not be parsed; overwriting.", output_path)
            existing = []

    existing.append(record)

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, ensure_ascii=False)

    logger.info("Record saved to %s (%d total record(s)).", output_path, len(existing))
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Face-Verify-Chain: detect face -> reverse image search -> JSON record",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "image",
        help="Path to the input image (JPEG, PNG, BMP, …).",
    )
    parser.add_argument(
        "--output",
        default="match_record.json",
        metavar="FILE",
        help="Path to the output JSON file (default: match_record.json).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        metavar="N",
        help="Maximum number of reverse-search matches to retrieve (default: 5).",
    )
    parser.add_argument(
        "--model",
        choices=["hog", "cnn"],
        default="hog",
        help="face_recognition detection model: 'hog' (fast/CPU) or 'cnn' (accurate/GPU). Default: hog.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run face detection only; skip reverse image search (useful for testing without API keys).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logger.info("Input image : %s", args.image)
    logger.info("Output file : %s", args.output)
    logger.info("Max results : %d", args.max_results)
    logger.info("Model       : %s", args.model)
    logger.info("Dry run     : %s", args.dry_run)

    if args.dry_run:
        logger.info("=== DRY RUN: Face detection only ===")
        face_result = detect_and_encode(args.image, model=args.model)
        if face_result.error:
            logger.error("Face detection error: %s", face_result.error)
            return 1
        print(json.dumps(face_result.to_dict(), indent=2))
        return 0

    record = build_record(
        image_path=args.image,
        max_results=args.max_results,
        model=args.model,
    )

    output_path = save_record(record, args.output)
    print(json.dumps(record, indent=2))

    status = record.get("pipeline_status", "unknown")
    logger.info("Pipeline finished with status: %s", status)
    return 0 if status in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
