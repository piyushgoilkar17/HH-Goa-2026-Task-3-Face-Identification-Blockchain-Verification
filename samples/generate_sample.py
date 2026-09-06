"""
samples/generate_sample.py
--------------------------
Downloads a public-domain portrait image and saves it as `sample_face.jpg`
so you have a ready-made test image without needing to supply your own.

Run once:
    python samples/generate_sample.py

The image used is the Wikipedia portrait of Barack Obama (White House official
photo, in the public domain as a U.S. Government work).
"""

import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Run: pip install requests  — then retry.")
    sys.exit(1)

# Public-domain official White House portrait — reliable face detection target.
# Source: https://en.wikipedia.org/wiki/File:Official_portrait_of_Barack_Obama.jpg
# License: Public domain (U.S. Government work)
DEFAULT_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/"
    "President_Barack_Obama.jpg/440px-President_Barack_Obama.jpg"
)

DEST = Path(__file__).parent / "sample_face.jpg"


def download_sample(url: str, dest: Path) -> None:
    print(f"Downloading sample portrait from:\n  {url}")
    headers = {"User-Agent": "face-verify-chain/1.0 (sample downloader)"}
    resp = requests.get(url, headers=headers, timeout=30, stream=True)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    size_kb = dest.stat().st_size / 1024
    print(f"Saved to: {dest}  ({size_kb:.1f} KB)")
    print("Done! Run the pipeline with:")
    print(f"  python main.py {dest} --dry-run")


if __name__ == "__main__":
    # Allow passing a custom URL as first argument
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    download_sample(url, DEST)
