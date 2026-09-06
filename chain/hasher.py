"""
chain/hasher.py
---------------
Deterministic SHA-256 hashing of a face-match record.

The hash is computed over a canonical subset of fields so that:
  - re-running on the same data always produces the same hash
  - fields that differ per-run (e.g. pipeline_status) are excluded
  - the hash covers exactly what matters: identity + matched URL + timestamp

Canonical fields (in this fixed order):
    image_path | encoding_dim | bounding_box | source_url |
    matched_image_url | confidence_score | timestamp
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


def _canonical_bytes(record: dict) -> bytes:
    """
    Build a stable, deterministic byte string from the relevant fields.
    Any missing field is included as an empty string so the schema is fixed.
    """
    face = record.get("face_detection", {})
    top_match = record.get("top_match") or {}

    canonical = {
        "image_path":        str(record.get("image_path", "")),
        "encoding_dim":      int(face.get("encoding_dim", 0)),
        # Bounding box as a sorted JSON object for determinism
        "bounding_box":      json.dumps(face.get("bounding_box", {}), sort_keys=True),
        "source_url":        str(top_match.get("source_url", "")),
        "matched_image_url": str(top_match.get("matched_image_url", "") or ""),
        "confidence_score":  float(top_match.get("confidence_score", 0.0)),
        "timestamp":         str(top_match.get("timestamp", "")),
    }

    # Serialize as a compact, sorted-key JSON string for maximum determinism
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    logger.debug("Canonical payload: %s", serialized)
    return serialized.encode("utf-8")


def compute_hash(record: dict) -> str:
    """
    Compute the SHA-256 hash of the canonical record payload.

    Parameters
    ----------
    record : dict
        A single match record as produced by main.py (the dict that gets
        appended to match_record.json).

    Returns
    -------
    str
        Lowercase hex-encoded SHA-256 digest (64 chars).
    """
    payload = _canonical_bytes(record)
    digest = hashlib.sha256(payload).hexdigest()
    logger.info("SHA-256 hash: %s", digest)
    return digest


def compute_hash_from_file(json_path: Union[str, Path], index: int = -1) -> tuple[str, dict]:
    """
    Load match_record.json, pick a record by *index* (default: last), and hash it.

    Parameters
    ----------
    json_path : str | Path
        Path to the JSON file (array of records or single record).
    index : int
        Which record to hash. Default -1 = most recent.

    Returns
    -------
    tuple[str, dict]
        (hex_digest, record_dict)
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Record file not found: {json_path}")

    raw = json_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    if isinstance(data, list):
        record = data[index]
    else:
        record = data  # single-record file

    digest = compute_hash(record)
    return digest, record
