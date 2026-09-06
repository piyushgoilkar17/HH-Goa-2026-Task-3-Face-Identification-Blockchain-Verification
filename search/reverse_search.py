"""
search/reverse_search.py
------------------------
Performs a reverse image search using SerpAPI's Google Reverse Image Search.

Workflow
--------
1. Upload the face-crop image to a publicly accessible URL via a temporary
   imgbb.com upload (free, no account needed for small images).
   -- OR -- accept a pre-existing public URL for the image.
2. Submit that URL to SerpAPI's /search endpoint with engine=google_reverse_image.
3. Parse the results and return a list of SearchMatch records.

Required env vars
-----------------
  SERPAPI_KEY   — your SerpAPI API key
  IMGBB_KEY     — your imgbb API key (free at https://api.imgbb.com)
                  (only needed when searching by local file / base64 crop)
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SERPAPI_KEY: str = os.getenv("SERPAPI_KEY", "")
IMGBB_KEY: str = os.getenv("IMGBB_KEY", "")

SERPAPI_ENDPOINT = "https://serpapi.com/search"
IMGBB_ENDPOINT = "https://api.imgbb.com/1/upload"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SearchMatch:
    """A single result returned by the reverse image search."""

    source_url: str                            # page where the image was found
    thumbnail_url: Optional[str] = None        # thumbnail of the matched image
    title: Optional[str] = None                # page title
    snippet: Optional[str] = None              # short text snippet
    confidence_score: float = 0.0              # 0-1 heuristic based on position rank
    matched_image_url: Optional[str] = None    # direct URL of the matched image (if available)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "thumbnail_url": self.thumbnail_url,
            "matched_image_url": self.matched_image_url,
            "title": self.title,
            "snippet": self.snippet,
            "confidence_score": round(self.confidence_score, 4),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload_to_imgbb(image_b64: str, name: str = "face_crop") -> str:
    """
    Upload a base64-encoded image to imgbb and return the public direct URL.

    Raises
    ------
    RuntimeError
        If IMGBB_KEY is missing or upload fails.
    """
    if not IMGBB_KEY:
        raise RuntimeError(
            "IMGBB_KEY is not set. "
            "Get a free key at https://api.imgbb.com and add it to your .env file."
        )

    logger.info("Uploading face crop to imgbb for reverse search...")
    resp = requests.post(
        IMGBB_ENDPOINT,
        data={
            "key": IMGBB_KEY,
            "image": image_b64,
            "name": name,
            "expiration": 600,   # delete after 10 minutes
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"imgbb upload failed: {data}")

    url = data["data"]["url"]
    logger.info("Uploaded to imgbb: %s", url)
    return url


def _rank_to_confidence(rank: int, total: int) -> float:
    """
    Simple heuristic: first result gets 1.0, last gets ~0.1.
    Uses a decaying inverse formula.
    """
    if total <= 0:
        return 0.0
    return round(1.0 / (1.0 + rank * 0.5), 4)


# ---------------------------------------------------------------------------
# Core search function
# ---------------------------------------------------------------------------

def reverse_search_by_url(image_url: str, max_results: int = 5) -> list[SearchMatch]:
    """
    Run a reverse image search against *image_url* via SerpAPI.

    Parameters
    ----------
    image_url : str
        A publicly accessible URL of the image to search.
    max_results : int
        Maximum number of matches to return (capped by SerpAPI results).

    Returns
    -------
    list[SearchMatch]
        Ordered list of matches, best first. Empty list if no matches found.
    """
    if not SERPAPI_KEY:
        raise RuntimeError(
            "SERPAPI_KEY is not set. "
            "Sign up at https://serpapi.com and add the key to your .env file."
        )

    logger.info("Submitting reverse image search for URL: %s", image_url)

    params = {
        "engine": "google_reverse_image",
        "image_url": image_url,
        "api_key": SERPAPI_KEY,
        "num": max_results,
        "safe": "active",
    }

    resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    matches: list[SearchMatch] = []

    # SerpAPI returns inline_images, image_results, and/or organic_results
    # depending on what Google surfaces. We harvest all three.

    inline_images = data.get("inline_images", [])
    image_results = data.get("image_results", [])
    organic       = data.get("organic_results", [])

    all_results = []

    for item in inline_images:
        all_results.append({
            "source_url":        item.get("source", ""),
            "thumbnail_url":     item.get("thumbnail", ""),
            "matched_image_url": item.get("original", item.get("thumbnail", "")),
            "title":             item.get("title", ""),
            "snippet":           item.get("snippet", ""),
        })

    for item in image_results:
        all_results.append({
            "source_url":        item.get("link", ""),
            "thumbnail_url":     item.get("thumbnail", ""),
            "matched_image_url": item.get("original", ""),
            "title":             item.get("title", ""),
            "snippet":           item.get("snippet", ""),
        })

    for item in organic:
        all_results.append({
            "source_url":        item.get("link", ""),
            "thumbnail_url":     "",
            "matched_image_url": "",
            "title":             item.get("title", ""),
            "snippet":           item.get("snippet", ""),
        })

    total = len(all_results)
    for rank, r in enumerate(all_results[:max_results]):
        if not r["source_url"]:
            continue
        matches.append(
            SearchMatch(
                source_url=r["source_url"],
                thumbnail_url=r["thumbnail_url"] or None,
                matched_image_url=r["matched_image_url"] or None,
                title=r["title"] or None,
                snippet=r["snippet"] or None,
                confidence_score=_rank_to_confidence(rank, total),
            )
        )

    logger.info(
        "Reverse search returned %d raw result(s), parsed %d match(es).",
        total, len(matches),
    )
    return matches


def reverse_search_by_b64(face_crop_b64: str, max_results: int = 5) -> list[SearchMatch]:
    """
    Upload a base64 face crop to imgbb, then run a reverse image search.

    This is the primary entry-point when you have a local face crop rather
    than a pre-existing public URL.

    Parameters
    ----------
    face_crop_b64 : str
        Base64-encoded JPEG face crop (as produced by face_id.detect).
    max_results : int
        Maximum number of matches to return.

    Returns
    -------
    list[SearchMatch]
    """
    public_url = _upload_to_imgbb(face_crop_b64)
    return reverse_search_by_url(public_url, max_results=max_results)


# ---------------------------------------------------------------------------
# Quick smoke-test -- run this file directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/Gatto_europeo4.jpg/320px-Gatto_europeo4.jpg"
    results = reverse_search_by_url(test_url)
    print(json.dumps([r.to_dict() for r in results], indent=2))
