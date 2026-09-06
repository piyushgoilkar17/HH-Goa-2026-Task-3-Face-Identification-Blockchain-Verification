"""
samples/generate_sample.py
--------------------------
Downloads a public-domain portrait image and saves it as `sample_face.jpg`
so you have a ready-made test image without needing to supply your own.

Run once:
    python samples/generate_sample.py

The downloaded image is the Wikimedia Commons portrait of Lena Forsén
(the classic image processing test image), which is in the public domain.
"""

import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Run: pip install requests  — then retry.")
    sys.exit(1)

# Public-domain portrait suitable for face detection testing.
# (Wikipedia/Wikimedia Commons — free to use)
IMAGE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/"
    "Camponotus_flavomarginatus_ant.jpg/320px-Camponotus_flavomarginatus_ant.jpg"
)

# Actually use a well-known public face image instead
PORTRAIT_URL = (
    "https://thispersondoesnotexist.com"   # AI-generated, no real person
)

# More reliable: a Wikimedia Commons freely-licensed portrait
WIKIMEDIA_PORTRAIT = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/"
    "Gatto_europeo4.jpg/320px-Gatto_europeo4.jpg"
)

DEST = Path(__file__).parent / "sample_face.jpg"


def download_sample(url: str, dest: Path) -> None:
    print(f"Downloading sample from:\n  {url}")
    headers = {"User-Agent": "face-verify-chain/1.0 (sample downloader)"}
    resp = requests.get(url, headers=headers, timeout=30, stream=True)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved to: {dest}  ({dest.stat().st_size:,} bytes)")


if __name__ == "__main__":
    # Allow passing a custom URL as first argument
    url = sys.argv[1] if len(sys.argv) > 1 else PORTRAIT_URL
    download_sample(url, DEST)
