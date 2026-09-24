# MediPass — 28-step demo script

End-to-end walkthrough of every feature, patient ↔ provider. Uses the two
pre-verified demo accounts that the backend seeds on startup and the sample
documents in [`docs/demo-documents/`](demo-documents/) (fictional data;
regenerate with `backend/venv/Scripts/python.exe docs/demo-documents/make_samples.py`).

| Role | Email | Password |
|---|---|---|
| Patient | `patient@medipass.demo` | `Demo@123` |
| Doctor | `doctor@medipass.demo` | `Demo@123` |

**Tip:** keep the patient in a normal window and the doctor in a private /
incognito window so you can switch without logging out.

**Before a live demo:** start from a fresh database (stop the backend, delete
`backend/medipass.db` and `backend/uploads/`, start it again), and check your
Gemini quota. On the free tier the model allows ~20 requests/day; when it's
exhausted every AI feature falls back automatically (see
[If Gemini is unavailable](#if-gemini-is-unavailable)).

## A. Patient builds their record

| # | Who | Action | Expected |
|---|---|---|---|
| 1 | Patient | Log in. | **Dashboard** opens: welcome message, all six counters at 0. |
| 2 | Patient | **Upload a document** → drag `prescription.png` onto the drop zone → type *Prescription* → **Upload document**. | Drop zone highlights while dragging; preview appears; button steps through *Uploading… → Analyzing… → Extracting… → Checking confidence…*; "Detected as prescription". |
| 3 | Patient | Upload `lab_report.pdf` as *Lab report* (drag-drop or **Choose file**). | "Detected as lab report". |
| 4 | Patient | Upload an X-ray image (any chest/knee/hand X-ray JPEG or PNG, or a `.dcm` DICOM file) as *Lab report*. | One record titled e.g. "X-ray of Chest". **Verify records** badge shows the number of pending records. |
| 5 | Patient | Open **Verify records**. Click **View source** on any card. | Every record shows a confidence score; any low-confidence record carries a "Low confidence — please check" warning. The X-ray card has a **Body part shown in this image** dropdown pre-filled with the suggestion and where it came from (AI / DICOM tag). View source opens the original file (DICOM is rendered as an image). |
| 6 | Patient | On the low-confidence medicine click **Edit before confirming**, fill *Timing*, **Save correction and confirm**. Check the X-ray's body part (change it if wrong) and **Confirm**. **Remove** any junk "Note from…" entries. **Confirm as-is** the rest. | Queue empties; badge clears. An X-ray whose body part is still "not identified" can't be confirmed until one is chosen. |
| 7 | Patient | **Your timeline**. | Verified records in date order, colour-coded by source, medicines/diagnoses grouped per date, each with **View source**. |
| 8 | Patient | **Medications**. | Only medication records. |
| 9 | Patient | **Lab results**. | Lab results with values and reference ranges, plus the X-ray with "Body part: Chest · confirmed by patient". |
| 10 | Patient | **Dashboard**. | Counters reflect the new data (recent events, active medications in the last 90 days). Tiles are clickable. |

## B. Doctor requests access

| # | Who | Action | Expected |
|---|---|---|---|
| 11 | Doctor | Log in. | Provider **Dashboard**: 0 active patients; **Add Consultation** is disabled until a patient approves. |
| 12 | Doctor | **Request Patient Access** → search `patient@medipass.demo` → **Request access**. | "Requested!". |
| 13 | Doctor | **Dashboard**. | *Pending requests* = 1 and a "Waiting for patient approval" list. |

## C. Patient grants scoped consent

| # | Who | Action | Expected |
|---|---|---|---|
| 14 | Patient | Look at the sidebar. | **Access requests** shows a red badge. |
| 15 | Patient | Open **Access requests**. | The request shows an **AI Sharing Recommendation** for the doctor's specialty. |
| 16 | Patient | Select *medications*, *allergies*, *diagnoses* (not labs) → **Approve access**. | Moves to "Providers with access history" as Approved with that scope; badge clears. |
| 17 | Patient | **Dashboard**. | *Active sharing sessions* = 1 and a "Who can see your records" list. |

## D. Doctor works with the shared record

| # | Who | Action | Expected |
|---|---|---|---|
| 18 | Doctor | **Dashboard**. | *Patients with active access* = 1; the patient is listed with their sharing scope. |
| 19 | Doctor | **View patient**. | Timeline shows medications, allergy and diagnoses only — **no lab results or X-rays** (not shared). |
| 20 | Doctor | Read the **AI Clinical Summary**; click a citation link. | Summary cites records; clicking a link highlights that record in the timeline. |
| 21 | Doctor | Back to **Dashboard** → **Add Consultation**. Either click the 🎙 mic and dictate a note, or type a *Consultation note* (title + details) → **Add to timeline**. | Page jumps straight to the form. Mic: "Checking your microphone…", then a live input-level bar and the device name while recording; **Stop & Process** → structured fields to apply. "Added to the patient's timeline". |
| 22 | Doctor | Add an *Allergy* record with details `No known allergies`. | Added (this deliberately contradicts the uploaded sulfa allergy). |
| 23 | Doctor | **Dashboard**. | **Recent consultations** lists both new records. (If the doctor's name matches the prescribing doctor on an uploaded prescription, the note shows **🔗 Related documents** linked to it — see `docs/CONSULTATION_PRESCRIPTION_LINKS.md`.) |

## E. Patient sees the result, adds a doctor by QR, revokes

| # | Who | Action | Expected |
|---|---|---|---|
| 24 | Patient | **Notifications** (badge = 2) → **Mark read**. | "Dr. Demo Doctor added a new consultation record: …" with local timestamps; badge clears. |
| 25 | Patient | **Your timeline**. | Conflict flag: *"One record states 'no known allergies' but another documents a specific allergy. Please reconcile."* — nothing silently resolved. |
| 26 | Patient | **My QR code** → keep *medications, allergies, diagnoses*, 30 days → **Generate my QR code**. | QR code, what it shares, and a countdown. |
| 27 | Doctor | **📷 Scan Patient QR** → **Start camera** (or **Upload a photo of the code**) and scan the patient's screen. | Back on the dashboard: green *"✓ Demo Patient access renewed / added to your patients"* banner, patient highlighted, no access request. Patient's screen: *"✓ Dr. Demo Doctor scanned your code"* + a notification. |
| 28 | Patient | **Activity log**, then **Access requests → Revoke** the doctor. Doctor: open the patient again. | Log shows *requested → approved → added a new record ×2 → you created a QR code → a doctor added you by scanning your QR code* → *access was revoked*. Doctor now gets "No approved access grant" and the patient disappears from their dashboard. |

## If Gemini is unavailable

Every AI feature has a fallback, so the demo still runs end-to-end:

| Feature | Fallback |
|---|---|
| Any Gemini call | 503 "model overloaded" is retried twice (1 s, 3 s), then the backup model (`MEDIPASS_GEMINI_FALLBACK_MODELS`, default `gemini-2.5-flash`) is tried; quota / model-not-found errors go straight to the backup. Only if every model fails do the fallbacks below kick in. |
| Document extraction (steps 2–3) | Local OCR (Tesseract for images, PyMuPDF for text PDFs) + rule-based extraction. Confidence comes from Tesseract per line. |
| X-ray (step 4) | DICOM files: body part from the `BodyPartExamined` tag. JPEG/PNG: a textless image uploaded as a lab report becomes an X-ray record with the body part **not identified** (or read from a printed label like "CHEST PA"); the patient picks it in step 6. |
| Sharing recommendation (step 15) | Rule-based minimum-necessary scope by specialty, labelled as such. |
| Clinical summary (step 20) | Factual digest of the shared records with the same citation links, labelled "AI summary is unavailable right now". |
| Voice dictation (provider form) | Raw transcript placed in notes for manual editing. |

Tesseract must be installed for photo uploads on the fallback path — see
`backend/README.md` → "Installing Tesseract".

## Last verified run — 2026-09-23

Run in the in-app browser against a throwaway database, sample documents
above. Gemini's free-tier daily quota was exhausted at the time, so steps 2–4,
15 and 20 exercised the fallbacks (the Gemini path itself was verified live
earlier the same day: extraction, confidence scores and the sharing
recommendation).

| Steps | Result | Notes |
|---|---|---|
| 1–4 | ✅ | Uploads 0.6–2.1 s on the OCR path. |
| 5–6 | ✅ | 19 records; Cetirizine at 64 % flagged low-confidence; View source returned the exact original file; 1 edited, 4 removed, 14 confirmed. |
| 7–10 | ✅ | 5 medication rows, 6 lab results; dashboard 5 recent events / 3 active meds. |
| 11–14 | ✅ | |
| 15 | ✅ after fix | Was a 500 error when Gemini is down → now rule-based fallback. |
| 16–19 | ✅ | Scope enforced: no lab/hospitalization records visible to the doctor. |
| 20 | ✅ after fix | Was "Failed to generate summary" → now cited factual digest (9 working citation links). |
| 21 | ✅ after fix | Form scroll re-applies after the summary/timeline load. |
| 22–28 | ✅ | Conflict flagged; revoke → provider gets 403 and dashboard list empties. (Steps 26–27 were re-verified with the QR flow: photo upload and link paths; the live-camera path needs a real camera.) |

Not covered by this run: voice dictation with a real microphone (the
diagnostics and error paths were exercised in the browser without one), and the
register / email-verification / password-reset screens (covered by
`backend/test_smoke.py` at the API level; registration sends real email when
SMTP is configured).
