"""
tests/test_hasher.py
---------------------
Unit tests for chain.hasher — does NOT require face_recognition, web3, or a chain.
Run with:   python -m pytest tests/ -v
        or: python tests/test_hasher.py
"""

import json
import sys
import hashlib
from pathlib import Path

# Allow running from project root without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from chain.hasher import compute_hash, compute_hash_from_file

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RECORD = {
    "pipeline_status": "success",
    "image_path": "samples/sample_face.jpg",
    "started_at": "2024-01-01T00:00:00Z",
    "finished_at": "2024-01-01T00:00:05Z",
    "face_detection": {
        "num_faces_in_image": 1,
        "bounding_box": {"top": 50, "right": 200, "bottom": 250, "left": 100},
        "encoding_dim": 128,
        "encoding": [0.1] * 128,
        "face_crop_b64": "AAABBB==",
    },
    "reverse_search": {
        "search_error": None,
        "num_matches": 1,
        "matches": [
            {
                "source_url": "https://example.com/photo",
                "matched_image_url": "https://example.com/photo.jpg",
                "confidence_score": 1.0,
                "timestamp": "2024-01-01T00:00:03Z",
            }
        ],
    },
    "top_match": {
        "source_url": "https://example.com/photo",
        "matched_image_url": "https://example.com/photo.jpg",
        "confidence_score": 1.0,
        "timestamp": "2024-01-01T00:00:03Z",
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_hash_is_64_hex_chars():
    h = compute_hash(SAMPLE_RECORD)
    assert len(h) == 64, f"Expected 64 chars, got {len(h)}"
    assert all(c in "0123456789abcdef" for c in h), "Hash is not lowercase hex"
    print(f"  ✅  hash length & format OK: {h[:16]}...")


def test_hash_is_deterministic():
    h1 = compute_hash(SAMPLE_RECORD)
    h2 = compute_hash(SAMPLE_RECORD)
    assert h1 == h2, "Same input produced different hashes!"
    print("  ✅  determinism OK")


def test_hash_changes_on_url_change():
    import copy
    modified = copy.deepcopy(SAMPLE_RECORD)
    modified["top_match"]["source_url"] = "https://attacker.com/tampered"
    h_orig = compute_hash(SAMPLE_RECORD)
    h_mod  = compute_hash(modified)
    assert h_orig != h_mod, "Tampered URL should produce a different hash!"
    print("  ✅  tamper sensitivity OK (URL change detected)")


def test_hash_changes_on_confidence_change():
    import copy
    modified = copy.deepcopy(SAMPLE_RECORD)
    modified["top_match"]["confidence_score"] = 0.0
    h_orig = compute_hash(SAMPLE_RECORD)
    h_mod  = compute_hash(modified)
    assert h_orig != h_mod, "Confidence change should produce a different hash!"
    print("  ✅  tamper sensitivity OK (confidence change detected)")


def test_hash_ignores_pipeline_status():
    """Fields like pipeline_status are excluded from the hash intentionally."""
    import copy
    r2 = copy.deepcopy(SAMPLE_RECORD)
    r2["pipeline_status"] = "partial"    # irrelevant field
    r2["started_at"]      = "1970-01-01T00:00:00Z"  # also excluded
    h1 = compute_hash(SAMPLE_RECORD)
    h2 = compute_hash(r2)
    assert h1 == h2, "Non-canonical fields should not affect hash"
    print("  ✅  non-canonical field exclusion OK")


def test_hash_no_top_match():
    """A record with no top_match (search failed) should still hash fine."""
    import copy
    r = copy.deepcopy(SAMPLE_RECORD)
    r["top_match"] = None
    h = compute_hash(r)
    assert len(h) == 64
    print("  ✅  None top_match OK")


def test_hash_from_file(tmp_path):
    """Write a JSON file and hash from it."""
    p = tmp_path / "match_record.json"
    p.write_text(json.dumps([SAMPLE_RECORD]), encoding="utf-8")
    h, rec = compute_hash_from_file(str(p))
    assert len(h) == 64
    assert rec["image_path"] == "samples/sample_face.jpg"
    print("  ✅  compute_hash_from_file OK")


# ---------------------------------------------------------------------------
# Simple runner (no pytest required)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile, os

    tests = [
        test_hash_is_64_hex_chars,
        test_hash_is_deterministic,
        test_hash_changes_on_url_change,
        test_hash_changes_on_confidence_change,
        test_hash_ignores_pipeline_status,
        test_hash_no_top_match,
    ]

    # test_hash_from_file needs tmp_path — handle manually
    with tempfile.TemporaryDirectory() as d:
        class FakePath:
            def __truediv__(self, name): return Path(d) / name
        test_hash_from_file(FakePath())

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥  {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
