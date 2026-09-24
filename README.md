# MediPass — Prototype

AI-assisted, patient-controlled medical history platform. See
`docs/REQUIREMENTS.md` for the full requirements this build implements.

## Quick start

Two servers, two terminals. First time only, create `backend/.env` from
`backend/.env.example` and fill in your Gemini key.

```bash
# Terminal 1 — backend (run from inside backend/)
cd backend
python -m venv venv                              # first time only
./venv/Scripts/python.exe -m pip install -r requirements.txt   # first time only (macOS/Linux: ./venv/bin/python)
./venv/Scripts/python.exe -m uvicorn app.main:app --reload

# Terminal 2 — frontend
cd frontend
npm install                                      # first time only
npm run dev
```

Open **http://localhost:5173** (the backend only accepts that origin) and log
in with a seeded demo account: `patient@medipass.demo` / `Demo@123` or
`doctor@medipass.demo` / `Demo@123`.

For photo uploads to work when Gemini is unavailable, install Tesseract — see
`backend/README.md` "Installing Tesseract".

## Demo

[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) is a 28-step walkthrough of every
feature with expected results, using the sample documents in
`docs/demo-documents/`.

## What's built

| Area | Status |
|---|---|
| Auth, email verification, password reset, seeded demo accounts | ✅ |
| Document upload (drag-drop / camera / file) → Gemini extraction with per-record confidence | ✅ |
| Fallback when Gemini fails: local OCR (Tesseract + PyMuPDF) + rule-based extraction | ✅ |
| Prescriptions, lab reports, X-ray images (JPEG/PNG/DICOM) with patient-confirmed body part (asked for X-ray/scan lab results only, never for a prescription's medicines, diagnoses or advice) | ✅ |
| Patient verification, timeline with conflict flags, sorting (date, recently added, record type) and type filter; Medications / Lab results views | ✅ |
| Consent-based, scoped provider access; provider-added records; patient notifications | ✅ |
| AI sharing recommendation on each access request, based on the doctor's whole verified profile (qualification, education, hospital), not just the Specialty field | ✅ |
| Patient QR code → doctor scans → patient added instantly (scoped, single-use, audited); an 8-character code above the QR (e.g. `K7Q4-M9TX`) can be typed instead of scanning — see [`docs/QR_PATIENT_ADD.md`](docs/QR_PATIENT_ADD.md) | ✅ |
| Consultation notes auto-linked to the same doctor's uploaded prescription (doctor + hospital matching, patient must accept; accepted links are final); the linked consultation appears as an extra entry under the prescription on the timeline — see [`docs/CONSULTATION_PRESCRIPTION_LINKS.md`](docs/CONSULTATION_PRESCRIPTION_LINKS.md) | ✅ |
| Voice dictation with AI structuring, rule-based fallback when Gemini is unavailable | ✅ |
| Doctor verification (specialization, hospital, registration, education, certificate) with a printable verification document and compliance checks; reviewers approve in the app (**Review doctors** screen) or straight from the review email, no MediPass account needed — see [`docs/DOCTOR_VERIFICATION.md`](docs/DOCTOR_VERIFICATION.md) | ✅ |
| Doctor's Active Patients list (status: critical / follow-up required / new / ongoing, filter, sort, inactive patients) — see [`docs/ACTIVE_PATIENTS.md`](docs/ACTIVE_PATIENTS.md) | ✅ |
| Treatment-course day counts and how extraction confidence is scored — see [`docs/DAYS_AND_CONFIDENCE.md`](docs/DAYS_AND_CONFIDENCE.md) | ✅ |
| Duplicate protection: same file blocked at upload, repeated entries flagged in Verify records, cleanup script — see [`docs/DUPLICATES.md`](docs/DUPLICATES.md) | ✅ |
| Patient can fill in / correct a prescription's doctor and hospital (re-runs linking) | ✅ |
| Patient & provider dashboards, audit log | ✅ |
| Doctor notifications: sidebar badge and dashboard bar when a patient approves, declines or revokes access, and for the verification outcome; **Mark all read** for patients and doctors | ✅ |
| Intro screen: the main link shows a 5-second MediPass intro (with **Skip**) before the login page, once per browser tab | ✅ |
| Phone-friendly layout: compact top bar with a swipeable menu pinned to the top, two-column dashboard cards, every page fits a phone screen | ✅ |
| Deployed on Railway (backend + frontend, no Docker): [app](https://medipass-frontend-production.up.railway.app) · [API health](https://medipass-ai-production.up.railway.app/health); email sent through Brevo's HTTPS API, since Railway blocks SMTP — see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | ✅ |
| Full manual test checklist (every feature, live or local) — see [`docs/TEST_CHECKLIST.md`](docs/TEST_CHECKLIST.md) | ✅ |
| Hospitals/labs as roles, ABDM interoperability | Out of scope (see `docs/REQUIREMENTS.md` §7) |

## Verifying it works

```bash
cd backend
./venv/Scripts/python.exe test_smoke.py
```

Runs the whole journey against a throwaway database (Gemini mocked by default;
`SMOKE_USE_REAL_GEMINI=1` for the live API) and should print
`ALL CHECKS PASSED`.
