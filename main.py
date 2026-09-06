"""
main.py
-------
Face-Verify-Chain — full pipeline entry point.

Pipeline
--------
    1. face_id.detect       — detect + encode face (128-d vector + crop)
    2. search.reverse_search — reverse image search via SerpAPI / imgbb
    3. Save results          → match_record.json
    4. chain.hasher          — compute SHA-256 of the match record
    5. chain.anchor          — anchor hash on-chain (Ganache / Polygon Amoy / any EVM)
    6. chain.verify          — re-query chain and print VERIFIED / TAMPERED / NOT FOUND

Usage
-----
    python main.py <image_path> [options]

Examples
--------
    # Full pipeline (needs SerpAPI + imgbb + Ganache running):
    python main.py samples/sample_face.jpg

    # Face detection only (no API keys needed):
    python main.py samples/sample_face.jpg --dry-run

    # Face detect + search + hash + anchor + verify (skip nothing):
    python main.py samples/sample_face.jpg --max-results 5

    # Skip web search, go straight to chain steps on an existing record:
    python main.py samples/sample_face.jpg --skip-search --output match_record.json

Flags
-----
    --dry-run       Face detection only (no search, no chain)
    --skip-search   Load existing match_record.json, skip search step
    --skip-chain    Run face detect + search, skip anchoring + verification
    --output FILE   JSON output path (default: match_record.json)
    --max-results N Max reverse-search results (default: 5)
    --model         Facenet | VGG-Face | ArcFace  [default: Facenet]
    --scan-blocks N Blocks to scan for calldata verification (default: 200)
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

# ANSI helpers
BOLD  = "\033[1m"
CYAN  = "\033[96m"
RESET = "\033[0m"

def _section(title: str) -> None:
    logger.info("%s=== %s ===%s", BOLD + CYAN, title, RESET)


# ---------------------------------------------------------------------------
# Step 1 + 2 — detect & search (unchanged from v1)
# ---------------------------------------------------------------------------

def build_record(image_path: str, max_results: int, model: str) -> dict:
    """Run face detection + reverse image search; return the record dict."""
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    _section("STEP 1: Face Detection")
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
        "Face detected: %d face(s). Encoding dim=%d.",
        face_result.num_faces_in_image,
        len(face_result.encoding),
    )

    _section("STEP 2: Reverse Image Search")
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

    record = {
        "pipeline_status": "success" if not search_error else "partial",
        "image_path": image_path,
        "started_at": started_at,
        "finished_at": finished_at,
        "face_detection": {
            "num_faces_in_image": face_result.num_faces_in_image,
            "bounding_box": face_result.bounding_box,
            "encoding_dim": len(face_result.encoding),
            "encoding": face_result.encoding,
            "face_crop_b64": face_result.face_crop_b64,
        },
        "reverse_search": {
            "search_error": search_error,
            "num_matches": len(matches),
            "matches": [m.to_dict() for m in matches],
        },
        "top_match": matches[0].to_dict() if matches else None,
    }
    return record


# ---------------------------------------------------------------------------
# Step 3 — JSON persistence
# ---------------------------------------------------------------------------

def save_record(record: dict, output_path: str | Path) -> Path:
    """Append *record* to the JSON array at *output_path* (creates if absent)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if output_path.exists() and output_path.stat().st_size > 0:
        try:
            with output_path.open("r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = [existing]
        except json.JSONDecodeError:
            logger.warning("Existing %s could not be parsed; overwriting.", output_path)

    existing.append(record)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, ensure_ascii=False)

    logger.info("Record saved → %s (%d total).", output_path, len(existing))
    return output_path


# ---------------------------------------------------------------------------
# Step 4 — SHA-256 hash
# ---------------------------------------------------------------------------

def hash_record(record: dict) -> str:
    """Compute and log the canonical SHA-256 of *record*."""
    _section("STEP 4: SHA-256 Hashing")
    from chain.hasher import compute_hash
    hex_digest = compute_hash(record)
    logger.info("SHA-256: %s", hex_digest)
    return hex_digest


# ---------------------------------------------------------------------------
# Step 5 — On-chain anchoring
# ---------------------------------------------------------------------------

def anchor_on_chain(hex_digest: str) -> dict | None:
    """
    Anchor *hex_digest* on-chain. Returns anchor metadata dict, or None on error.
    """
    _section("STEP 5: On-Chain Anchoring")
    try:
        from chain.anchor import anchor_record
        result = anchor_record(hex_digest)
        logger.info(
            "Anchored!  tx=%s  block=%s  gas=%s",
            result["tx_hash"], result["block_number"], result["gas_used"],
        )
        return result
    except RuntimeError as exc:
        logger.error("Anchoring failed: %s", exc)
        return None
    except Exception as exc:
        logger.exception("Unexpected anchoring error.")
        return None


# ---------------------------------------------------------------------------
# Step 6 — On-chain verification
# ---------------------------------------------------------------------------

def verify_on_chain(hex_digest: str, scan_blocks: int = 200) -> dict | None:
    """Re-query the chain and print a clear VERIFIED / TAMPERED / NOT FOUND result."""
    _section("STEP 6: On-Chain Verification")
    try:
        from chain.verify import verify_record, print_result
        result = verify_record(hex_digest, scan_blocks=scan_blocks)
        print_result(result)
        return result
    except RuntimeError as exc:
        logger.error("Verification failed: %s", exc)
        return None
    except Exception as exc:
        logger.exception("Unexpected verification error.")
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Face-Verify-Chain: detect → search → anchor → verify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("image", help="Path to the input image (JPEG, PNG, …).")
    parser.add_argument(
        "--output", default="match_record.json", metavar="FILE",
        help="Output JSON file (default: match_record.json).",
    )
    parser.add_argument(
        "--max-results", type=int, default=5, metavar="N",
        help="Max reverse-search matches (default: 5).",
    )
    parser.add_argument(
        "--model", choices=["Facenet", "VGG-Face", "ArcFace"], default="Facenet",
        help="DeepFace embedding model (default: Facenet).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Face detection only — skip search, hashing, and chain steps.",
    )
    parser.add_argument(
        "--skip-search", action="store_true",
        help="Skip reverse image search (useful if match_record.json already exists).",
    )
    parser.add_argument(
        "--skip-chain", action="store_true",
        help="Skip on-chain anchoring and verification.",
    )
    parser.add_argument(
        "--scan-blocks", type=int, default=200, metavar="N",
        help="(calldata mode) Blocks to scan during verification (default: 200).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    logger.info("Input image  : %s", args.image)
    logger.info("Output file  : %s", args.output)
    logger.info("Max results  : %d", args.max_results)
    logger.info("Model        : %s", args.model)
    logger.info("Dry run      : %s", args.dry_run)
    logger.info("Skip search  : %s", args.skip_search)
    logger.info("Skip chain   : %s", args.skip_chain)

    # ── Dry-run: face detection only ────────────────────────────────────────
    if args.dry_run:
        _section("DRY RUN — Face Detection Only")
        face_result = detect_and_encode(args.image, model=args.model)
        if face_result.error:
            logger.error("Face detection error: %s", face_result.error)
            return 1
        print(json.dumps(face_result.to_dict(), indent=2))
        return 0

    # ── Normal run ──────────────────────────────────────────────────────────
    output_path = Path(args.output)

    if args.skip_search and output_path.exists():
        # Load the most recent record from the existing file
        _section("Loading existing match_record.json (--skip-search)")
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        record = existing[-1] if isinstance(existing, list) else existing
    else:
        # Steps 1 + 2: detect + search
        record = build_record(
            image_path=args.image,
            max_results=args.max_results,
            model=args.model,
        )
        if record.get("pipeline_status") == "failed":
            logger.error("Pipeline failed at face detection stage.")
            return 1
        # Step 3: persist
        save_record(record, output_path)

    print(json.dumps(record, indent=2))

    if args.skip_chain:
        logger.info("--skip-chain set; stopping before anchoring.")
        return 0

    # Step 4: hash
    hex_digest = hash_record(record)

    # Step 5: anchor
    anchor_meta = anchor_on_chain(hex_digest)
    if anchor_meta is None:
        logger.warning(
            "Anchoring failed or skipped. "
            "Is Ganache running?  →  npx ganache\n"
            "Set CHAIN_BACKEND, CHAIN_RPC_URL, CHAIN_PRIVATE_KEY in .env for other chains."
        )
        return 1

    # Persist anchor metadata alongside the record
    record["chain_anchor"] = anchor_meta
    save_record(record, output_path)

    # Step 6: verify
    verify_result = verify_on_chain(hex_digest, scan_blocks=args.scan_blocks)

    if verify_result:
        record["chain_verify"] = verify_result
        save_record(record, output_path)

    status = record.get("pipeline_status", "unknown")
    logger.info("Pipeline finished. Status: %s", status)
    return 0 if status in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
