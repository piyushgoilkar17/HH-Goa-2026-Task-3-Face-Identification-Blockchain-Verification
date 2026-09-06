# face-verify-chain

A Python pipeline that:
1. **Detects and encodes** a face in an input image (128-d vector via `face_recognition`)
2. **Reverse-searches** the face online via SerpAPI (Google Reverse Image Search)
3. **Saves results** — source URL, matched image, timestamp, confidence score — to `match_record.json`

---

## Project Structure

```
face-verify-chain/
├── face_id/
│   ├── __init__.py
│   └── detect.py          # Face detection & 128-d encoding
├── search/
│   ├── __init__.py
│   └── reverse_search.py  # Reverse image search via SerpAPI + imgbb
├── samples/
│   ├── generate_sample.py # Helper to download a test image
│   └── README.md
├── main.py                # Pipeline entry point
├── requirements.txt
├── .env.example           # Copy to .env and fill in your keys
└── .gitignore
```

---

## Setup

### 1. Clone & create a virtual environment

```bash
git clone <repo-url> face-verify-chain
cd face-verify-chain
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

> **Apple Silicon (M1/M2) note:** `dlib` must be compiled.
> Run: `brew install cmake` first, then the pip install below will build dlib from source automatically.

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in:
#   SERPAPI_KEY  — https://serpapi.com (free tier: 100 searches/month)
#   IMGBB_KEY    — https://api.imgbb.com (free)
```

### 4. Download a sample test image

```bash
python samples/generate_sample.py
# OR provide your own image as samples/sample_face.jpg
```

---

## Usage

```bash
# Full pipeline: detect → reverse search → save JSON
python main.py samples/sample_face.jpg

# Custom output path
python main.py samples/sample_face.jpg --output results/my_run.json

# Dry run: face detection only (no API keys needed)
python main.py samples/sample_face.jpg --dry-run

# Use CNN model (more accurate, requires GPU / dlib with CUDA)
python main.py samples/sample_face.jpg --model cnn

# More search results
python main.py samples/sample_face.jpg --max-results 10
```

---

## Output: `match_record.json`

Each run **appends** a record to `match_record.json` (a JSON array). Example:

```json
[
  {
    "pipeline_status": "success",
    "image_path": "samples/sample_face.jpg",
    "started_at": "2026-09-06T09:00:00Z",
    "finished_at": "2026-09-06T09:00:05Z",
    "face_detection": {
      "num_faces_in_image": 1,
      "bounding_box": { "top": 48, "right": 210, "bottom": 180, "left": 78 },
      "encoding_dim": 128,
      "encoding": [ ... ],
      "face_crop_b64": "..."
    },
    "reverse_search": {
      "search_error": null,
      "num_matches": 3,
      "matches": [
        {
          "source_url": "https://example.com/page-with-photo",
          "thumbnail_url": "https://...",
          "matched_image_url": "https://...",
          "title": "Profile page",
          "snippet": "...",
          "confidence_score": 1.0,
          "timestamp": "2026-09-06T09:00:04Z"
        }
      ]
    },
    "top_match": { ... }
  }
]
```

---

## API Keys Required

| Key | Where to get it | Cost |
|-----|----------------|------|
| `SERPAPI_KEY` | [serpapi.com](https://serpapi.com) | Free tier: 100 searches/month |
| `IMGBB_KEY` | [api.imgbb.com](https://api.imgbb.com) | Free |

---

## Module Smoke Tests

```bash
# Test face detection only
python face_id/detect.py samples/sample_face.jpg

# Test reverse search only (needs SERPAPI_KEY + IMGBB_KEY in .env)
python search/reverse_search.py https://example.com/some-face-image.jpg
```

---

## Roadmap

- [ ] Blockchain anchoring of match records (next phase)
- [ ] DeepFace multi-model backend option
- [ ] PimEyes / Google Vision API alternative search backends
- [ ] Confidence scoring calibration
- [ ] CLI progress bars with `rich`
