# MediPass Backend (Prototype)

FastAPI backend for MediPass: auth and email verification, document upload
with **Gemini multimodal extraction** (and a local **Tesseract + PyMuPDF OCR
fallback** when the AI is unavailable), patient verification, the timeline
(conflict detection, treatment courses, duplicates), scoped doctor access
(requests, QR / short codes, AI sharing recommendation), doctor verification
with reviewer approval, consultation-prescription linking, notifications,
the Active Patients board and the audit log.

## Installing Tesseract (required for OCR)

The Python packages (`pytesseract`, `Pillow`, `PyMuPDF`) are installed by
`pip install -r requirements.txt` above, but `pytesseract` is just a thin
wrapper — it needs the actual **Tesseract OCR engine** installed separately
on your machine (this is normal; it's how OCR wrappers work in every
language, not specific to this project).

**Windows:**
1. Install the UB-Mannheim build (the standard Windows build of Tesseract), either with
   `winget install --id UB-Mannheim.TesseractOCR -e` or from https://github.com/UB-Mannheim/tesseract/wiki
2. Default install location is `C:\Program Files\Tesseract-OCR`. The installer does **not** add it to PATH.
3. Either add that folder to your PATH, **or** point the backend at it in `backend/.env`:
   ```
   TESSERACT_CMD_PATH=C:/Program Files/Tesseract-OCR/tesseract.exe
   ```
4. If you changed PATH, restart your terminal / VS Code so it picks up the new value.

**macOS:**
```bash
brew install tesseract
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install tesseract-ocr
```

**Verify it worked**, from anywhere:
```bash
tesseract --version
```
If that prints a version number, you're set. If document upload later fails
with an error mentioning "Tesseract OCR engine isn't installed", it means
this step still needs doing — the app deliberately catches this and tells
you clearly rather than crashing.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is now at `http://127.0.0.1:8000`. Interactive docs (Swagger UI) are
at `http://127.0.0.1:8000/docs` — you can register users and try every
endpoint from there without writing any frontend code yet.

A SQLite file `medipass.db` is created automatically in this folder on first
run. Delete it any time to reset all data.

## Run the smoke test

```bash
python3 test_smoke.py
```

This runs the entire user journey (patient uploads a real generated image
and PDF, which run through actual OCR → patient verifies → provider
requests access → patient consents → provider views timeline and adds a
record → conflict gets flagged → patient revokes access → audit log
checked) against a throwaway database and uploads folder, and prints
PASS/FAIL for every step. It should print `ALL CHECKS PASSED` with no
failures.

Requires Tesseract to be installed (see above) — the image-upload check
will fail with a clear message if it isn't.

## Project layout

```
app/
  main.py            FastAPI app + router registration
  database.py         SQLAlchemy engine/session (SQLite by default)
  models.py            ORM tables
  schemas.py            Pydantic request/response models
  auth.py                Password hashing, JWT, role-based auth dependency
  llm.py                  Gemini: document extraction, sharing recommendation,
                          voice-note structuring, clinical summary; model
                          fallback chain and rule-based fallbacks
  ocr.py                  Fallback OCR: Tesseract for images, PyMuPDF (direct
                          text or render+OCR) for PDFs
  extraction.py            Rule-based extraction from OCR'd text (used when
                            Gemini is unavailable)
  confidence.py             Confidence scoring with reasons
  durations.py              Treatment-course and follow-up day counts
  duplicates.py             Duplicate file / record detection
  linking.py                Consultation-note <-> prescription matching
  imaging.py                 X-ray/DICOM: body-part vocabulary, DICOM decode,
                             reconciling AI vs DICOM-tag body part
  email_utils.py            Email via Brevo's HTTPS API, SMTP fallback
  storage.py                Saves uploaded files to disk, serves them back
  intelligence.py            Conflict detection for the timeline
  access_control.py            Shared consent check used by timeline & consultations
  serializers.py                 Converts ORM rows -> API response shapes
  routers/
    auth.py, documents.py, records.py, timeline.py, access.py,
    consultations.py, audit.py, users.py, notifications.py, links.py,
    patient_qr.py, doctor_verification.py, reviewer.py, provider_patients.py
```

## Environment variables (optional)

| Variable | Default | Purpose |
|---|---|---|
| `MEDIPASS_DATABASE_URL` | `sqlite:///./medipass.db` | Swap in Postgres etc. |
| `MEDIPASS_SECRET_KEY` | dev placeholder | JWT signing key — set a real secret before any real deployment. |
| `MEDIPASS_UPLOAD_DIR` | `./uploads` | Where uploaded documents are stored on disk. |

## What's real vs. what's still simplified

**Real now:**
- **File upload** — actual JPEG/PNG/PDF files, not pasted text. The
  frontend's upload page opens the device camera on mobile.
- **OCR** — genuine Tesseract OCR for images. For PDFs, embedded text is
  read directly when present (instant, no OCR needed — most lab
  PDF exports have this); scanned PDFs with no text layer are rendered to
  an image and OCR'd the same as a photo. See `app/ocr.py`.
- **Confidence scores** — real per-line averages of Tesseract's own
  per-word confidence output (0-100, normalized to 0.0-1.0), not a guess.
  A blurry photo genuinely produces a lower score. PDF-embedded text always
  scores 1.0, correctly, since there's no OCR uncertainty involved.
- **Source documents are stored and retrievable** — `GET
  /documents/{id}/file` streams back the original upload, which is what
  the frontend's "View source" button opens.

**Still simplified (by design, and clearly isolated so they're easy next
steps):**
- **Fallback extraction** (`app/extraction.py`) is regex/keyword-based and
  only runs when Gemini is unavailable. It looks for dose patterns,
  "allerg", "diagnos", etc., so it is less accurate than the AI path; its
  records get lower confidence and the patient checks them before they
  join the timeline.
- **X-ray body part** (`app/imaging.py`) is suggested by Gemini vision
  and/or the DICOM `BodyPartExamined` tag (the two are reconciled and
  disagreements flagged). No automatic method is 100% accurate, so every
  imaging record must be confirmed by the patient, who picks the body part
  if it couldn't be identified; the stored value is marked
  `body_part_source: patient_confirmed`. There's no offline image
  classifier -- with Gemini down, JPEG/PNG X-rays arrive "not identified".

## Next phases

- ABDM / ABHA interoperability
- Hospital and lab roles that push reports directly
- Multilingual extraction and voice notes
- PostgreSQL and encryption at rest for production scale
