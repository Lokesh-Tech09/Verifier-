# DrawTally API

Production-ready FastAPI backend for **DrawTally** — an engineering
drawing vs Bill of Materials (BOM) quantity verification system.

Upload a single-sheet PDF with the drawing on the left half and the BOM
table on the right half. DrawTally extracts quantities from both sides,
fuzzy-matches items across them, and returns a per-item tally report
flagging matches, mismatches, and items missing from either side.

## How extraction works

1. **Render** — each PDF page is rasterized at 300 DPI (PyMuPDF) and split
   down the middle: left half = drawing, right half = BOM.
2. **Drawing callouts** (left half) — OCR'd with Tesseract, then parsed
   with a set of regex patterns covering the common ways quantities are
   called out on a drawing (`4 - Bolt M8x20`, `6 pcs bracket`,
   `(3) gusset plate`, balloon callouts, etc).
3. **BOM table** (right half) — first tries PyMuPDF's native text-table
   finder (fast, no OCR needed, works well on digital/vector PDFs). If
   that finds nothing (e.g. a scanned drawing), it falls back to an
   OpenCV-based grid detector that finds the table's rule lines and OCRs
   each cell individually.
4. **Matching** — descriptions are normalized (lowercased, common
   structural/fastener abbreviations expanded, size specs optionally
   stripped) and compared with `rapidfuzz`; a piece-mark exact match
   short-circuits the fuzzy comparison when available.
5. **Tally** — for every matched pair, computes `drawing_qty - bom_qty`
   and flags `match` / `mismatch`; unmatched drawing callouts become
   `missing-bom`, unmatched BOM lines become `missing-drawing`.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# System dependency (not pip-installable): Tesseract OCR
# Debian/Ubuntu:
sudo apt-get install -y tesseract-ocr libgl1 libglib2.0-0

uvicorn app.main:app --reload
```

Then open **http://localhost:8000/docs** for interactive Swagger docs.

### Docker

```bash
docker compose up --build
```

## API

| Method | Path                        | Purpose                                   |
|--------|-----------------------------|--------------------------------------------|
| GET    | `/health`                   | Liveness/readiness check                   |
| POST   | `/api/upload`                | Upload a PDF, returns a `job_id`           |
| POST   | `/api/analyze/{job_id}`      | Extract drawing + BOM items, run matching  |
| GET    | `/api/status/{job_id}`       | Poll a job's status                        |
| POST   | `/api/tally`                  | Compare quantities, return the report      |
| POST   | `/api/export`                 | Download the report as CSV / JSON / PDF    |

All responses use a standard envelope:

```json
{ "success": true, "data": { ... }, "message": null, "error": null }
```

```json
{ "success": false, "data": null, "error": { "code": "...", "message": "...", "details": {} } }
```

### Example: upload → analyze → tally → export

```bash
JOB_ID=$(curl -s -F "pdf=@203412.pdf" http://localhost:8000/api/upload \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['job_id'])")

curl -s -X POST http://localhost:8000/api/analyze/$JOB_ID

TALLY=$(curl -s -X POST http://localhost:8000/api/tally \
  -H "Content-Type: application/json" -d "{\"job_id\":\"$JOB_ID\"}")

echo "$TALLY" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin)['data']['results'], indent=2))"

# Re-shape the results into an export request and download a PDF report:
python3 - <<PY
import json, requests
results = json.loads('''$TALLY''')["data"]["results"]
r = requests.post("http://localhost:8000/api/export",
                   json={"format": "pdf", "job_id": "$JOB_ID", "results": results})
open("report.pdf", "wb").write(r.content)
PY
```

## Configuration

All settings are environment variables (see `.env.example`), loaded via
`pydantic-settings`. Notable ones:

| Variable                   | Default          | Notes                                    |
|----------------------------|------------------|-------------------------------------------|
| `UPLOAD_MAX_SIZE`          | `52428800` (50MB)| Enforced while streaming, not just at the end |
| `TEMP_DIR`                 | `/tmp/drawtally` | Per-job upload storage                    |
| `TEMP_FILE_TTL`            | `300` (5 min)    | Background task deletes stale job dirs    |
| `OCR_DPI`                  | `300`            | Higher = more accurate OCR, slower render |
| `FUZZY_MATCH_THRESHOLD`    | `75`             | 0–100, rapidfuzz token-sort-ratio cutoff  |
| `RATE_LIMIT_PER_MINUTE`    | `10`             | Per-IP, applies to `/api/upload`          |
| `CORS_ORIGINS`             | `["*"]`          | **Restrict this in production**           |

## Testing

```bash
pip install -r requirements.txt   # includes pytest, pytest-asyncio, httpx
pytest -v
```

Tests cover: upload validation (magic-byte check, size limits, filename
sanitization), 404 handling for unknown jobs, the tally comparison logic
(match/mismatch/missing-both-directions), and an end-to-end upload →
analyze smoke test against a synthetically generated PDF.

## Notes on the reference implementation

- **Job storage is in-memory** (`app/services/job_store.py`), which is
  fine for the single-worker deployment shipped here. For a
  horizontally-scaled deployment, swap it for Redis — the router code
  doesn't need to change, only that one module.
- **Rate limiting** is a minimal in-memory sliding window suitable for a
  single instance; swap for `slowapi` + Redis (or your API gateway's rate
  limiter) behind a load balancer.
- **BOM table detection** favors PyMuPDF's native table finder first
  because it's dramatically more reliable than OCR-based cell detection
  on digital PDFs; the OpenCV grid detector is the fallback for scanned
  sheets, per the original spec.
