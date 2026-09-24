"""
End-to-end smoke test for the MediPass backend.

Run with:  python test_smoke.py

Exercises the full loop from REQUIREMENTS.md against the real FastAPI app:
register -> email verification gate -> login -> upload documents -> patient
verifies extracted records -> provider requests access -> patient approves a
scoped grant -> provider views (scope-filtered) timeline -> provider adds
records -> patient is notified -> conflict flagged -> doctor added instantly
by scanning the patient's QR code -> consultation notes auto-linked to
prescriptions -> treatment-course day counts and confidence scoring -> doctor
verification document -> Active Patients statuses -> patient revokes -> audit
log checked. Plus: X-ray / DICOM
body-part identification and its patient-confirmation gate, the removed
discharge-summary upload type, and Gemini 503 retry / model fallback.

Extraction paths
----------------
documents.py tries Gemini first and only falls back to local OCR +
regex extraction if Gemini fails. This test covers both, explicitly:

* Primary (Gemini) path: by default the Gemini client is replaced with a
  deterministic fake that returns canned structured output, so the test is
  repeatable, offline-safe and doesn't burn API quota. The REAL
  post-processing in llm.extract_medical_records still runs (confidence
  clamping, the <=0.6 cap for medications missing a dose, date parsing).
  Set SMOKE_USE_REAL_GEMINI=1 to hit the live API instead.
* OCR fallback path: Gemini is forced to fail, then
    - an embedded-text PDF goes through PyMuPDF text extraction (no
      Tesseract needed, always runs), and
    - a PNG goes through real Tesseract OCR -- SKIPPED with a notice if the
      Tesseract binary isn't installed (see README "Installing Tesseract").

Uses a throwaway SQLite file and uploads folder, and blanks the SMTP
credentials so no real emails are sent.
"""
import io
import json
import os
import shutil
import sys
from unittest import mock

from dotenv import load_dotenv

load_dotenv()  # pick up GEMINI_API_KEY etc. before we override below

os.environ["MEDIPASS_DATABASE_URL"] = "sqlite:///./smoke_test.db"
os.environ["MEDIPASS_UPLOAD_DIR"] = "./smoke_test_uploads"
# Exercise the real verification gate, whatever the local .env says.
os.environ["MEDIPASS_SKIP_EMAIL_VERIFICATION"] = "false"
# Never send real emails from a test run -- email_utils logs to console instead.
os.environ["SMTP_USERNAME"] = ""
os.environ["SMTP_PASSWORD"] = ""

USE_REAL_GEMINI = os.environ.get("SMOKE_USE_REAL_GEMINI") == "1"
if not USE_REAL_GEMINI:
    os.environ.setdefault("GEMINI_API_KEY", "smoke-test-dummy-key")

# start clean every run
if os.path.exists("smoke_test.db"):
    os.remove("smoke_test.db")
if os.path.exists("smoke_test_uploads"):
    shutil.rmtree("smoke_test_uploads")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import llm, models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.routers import documents as documents_router  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
import pymupdf  # noqa: E402
import pytesseract  # noqa: E402

client = TestClient(app)


def check(condition, message):
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)
    print(f"PASS: {message}")


# ---------------------------------------------------------------- fixtures

def make_test_prescription_png() -> bytes:
    img = Image.new("RGB", (620, 220), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
    draw.text((20, 20), "Amoxicillin 500mg", fill="black", font=font)
    draw.text((20, 70), "Patient has penicillin allergy", fill="black", font=font)
    draw.text((20, 120), "Diagnosed with mild hypertension", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_pdf(lines) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, text in enumerate(lines):
        page.insert_text((72, 100 + 30 * i), text, fontsize=14)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


LAB_REPORT_LINES = [
    "Date: 12/10/22",  # DD/MM/YY -> 2022-10-12, not 10 Dec
    "Reference Range: Hemoglobin 13-17 g/dL",
    "Result: Hemoglobin 14.2 g/dL within normal limits",
]


# Canned Gemini responses (only used when USE_REAL_GEMINI is False)
FAKE_PRESCRIPTION = {
    "document_type": "prescription",
    "records": [
        {"record_type": "medication", "title": "Amoxicillin 500mg",
         "details": {"medicine": "Amoxicillin", "dose": "500mg", "timing": "1-0-1"},
         "confidence": 0.93, "record_date": "2026-01-10"},
        # missing dose -> must be capped at 0.6 even though the model says 0.9
        {"record_type": "medication", "title": "Paracetamol",
         "details": {"medicine": "Paracetamol"}, "confidence": 0.9, "record_date": "2026-01-10"},
        {"record_type": "allergy", "title": "Allergy to Penicillin",
         "details": {"text": "Patient has penicillin allergy"}, "confidence": 0.95, "record_date": "2026-01-10"},
        {"record_type": "diagnosis", "title": "Mild hypertension",
         "details": {"text": "Diagnosed with mild hypertension"}, "confidence": 1.4, "record_date": "2026-01-10"},
    ],
}
FAKE_CHEST_XRAY = {
    "document_type": "lab_report",
    "records": [
        {"record_type": "lab_result", "title": "Chest radiograph",
         "details": {"modality": "xray", "body_part": "chest", "laterality": "not_applicable",
                     "view": "PA", "text": "Chest radiograph showing both lung fields and heart shadow."},
         "confidence": 0.95},
    ],
}


class FakeGemini:
    """Stands in for google.genai.Client: .models.generate_content(...)."""

    def __init__(self):
        self.next_payload = None
        self.models = self

    def generate_content(self, **kwargs):
        return mock.Mock(text=json.dumps(self.next_payload))


fake_gemini = FakeGemini()
if not USE_REAL_GEMINI:
    mock.patch.object(llm, "get_gemini_client", return_value=fake_gemini).start()
print(f"INFO: Gemini path = {'LIVE API' if USE_REAL_GEMINI else 'deterministic fake'}")


def make_blank_png() -> bytes:
    """A textless greyscale image -- stands in for an X-ray photo on the OCR path."""
    img = Image.new("L", (400, 300), color=90)
    ImageDraw.Draw(img).ellipse((80, 40, 320, 260), fill=170)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_dicom(body_part="CHEST", modality="CR") -> bytes:
    """Minimal valid DICOM (uncompressed) with a gradient image."""
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1"  # CR image storage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("x.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = modality
    ds.BodyPartExamined = body_part
    ds.ViewPosition = "PA"
    ds.StudyDate = "20260801"
    ds.PatientName = "Test^Smoke"
    pixels = (np.add.outer(np.arange(64), np.arange(64)) * 16).astype("uint16")
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def upload(file_name, data, content_type, document_type, headers, allow_duplicate=True):
    # Test fixtures reuse the same image bytes, so the duplicate-file check is
    # skipped by default; 13f tests it explicitly with allow_duplicate=False.
    return client.post(
        "/documents/upload",
        files={"file": (file_name, data, content_type)},
        data={"document_type": document_type, "allow_duplicate": str(allow_duplicate).lower()},
        headers=headers,
    )


def doc_raw_text(document_id) -> str:
    """raw_text isn't exposed by the API, so read it straight from the DB."""
    db = SessionLocal()
    try:
        return db.query(models.Document).filter(models.Document.id == document_id).first().raw_text or ""
    finally:
        db.close()


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 0. demo accounts
r = client.post("/auth/login", data={"username": "patient@medipass.demo", "password": "Demo@123"})
check(r.status_code == 200, "seeded demo patient can log in")
demo_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
r = client.post("/auth/login", data={"username": "doctor@medipass.demo", "password": "Demo@123"})
check(r.status_code == 200, "seeded demo provider can log in")
demo_doctor_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

# ---------------------------------------------------------------- 1. register
r = client.post("/auth/register", json={
    "email": "priya@example.com", "password": "pw12345",
    "full_name": "Priya Sharma", "role": "patient",
})
check(r.status_code == 201, "patient registration")
patient_id = r.json()["id"]

r = client.post("/auth/register", json={
    "email": "drkumar@example.com", "password": "pw12345",
    "full_name": "Dr. Kumar", "role": "provider",
})
check(r.status_code == 201, "provider registration")

# ---------------------------------------------------------------- 2. verification gate + login
r = client.post("/auth/login", data={"username": "priya@example.com", "password": "pw12345"})
check(r.status_code == 403, "unverified user is blocked from login")


def verify_email(email):
    db = SessionLocal()
    try:
        token = db.query(models.User).filter(models.User.email == email).first().verification_token
    finally:
        db.close()
    return client.post("/auth/verify-email", json={"token": token})


check(verify_email("priya@example.com").status_code == 200, "patient verifies email")
check(verify_email("drkumar@example.com").status_code == 200, "provider verifies email")

r = client.post("/auth/login", data={"username": "priya@example.com", "password": "pw12345"})
check(r.status_code == 200, "patient login")
patient_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

r = client.post("/auth/login", data={"username": "drkumar@example.com", "password": "pw12345"})
check(r.status_code == 200, "provider login")
provider_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

# ---------------------------------------------------------------- 3. primary (Gemini) extraction path
png_bytes = make_test_prescription_png()
fake_gemini.next_payload = FAKE_PRESCRIPTION
r = upload("prescription_2026.png", png_bytes, "image/png", "prescription", patient_headers)
check(r.status_code == 201, f"prescription upload via Gemini path (got {r.status_code}: {r.text[:200]})")
document_id = r.json()["id"]
check(doc_raw_text(document_id) == "Text extraction handled directly by LLM.", "prescription went through the Gemini path")

r = upload("discharge.pdf", make_pdf(["Discharge summary"]), "application/pdf", "discharge_summary", patient_headers)
check(r.status_code == 400, "discharge_summary is no longer an accepted upload type")

r = upload("x.png", png_bytes, "image/png", "auto", patient_headers)
check(r.status_code == 400, "unknown document_type is rejected")

# 3c. Fetch the original file back -- source traceability
r = client.get(f"/documents/{document_id}/file", headers=patient_headers)
check(r.status_code == 200 and r.headers["content-type"] == "image/png", "can fetch original uploaded file back")
check(r.content == png_bytes, "fetched file bytes match what was uploaded")

# ---------------------------------------------------------------- 3d. forced OCR fallback path
with mock.patch.object(documents_router, "extract_medical_records",
                       side_effect=RuntimeError("forced Gemini failure (smoke test)")):
    r = upload("lab_report.pdf", make_pdf(LAB_REPORT_LINES), "application/pdf", "lab_report", patient_headers)
    check(r.status_code == 201, f"OCR fallback: embedded-text PDF upload (got {r.status_code}: {r.text[:200]})")
    fallback_pdf_doc = r.json()["id"]
    check("Hemoglobin" in doc_raw_text(fallback_pdf_doc), "OCR fallback: PDF text extracted locally by PyMuPDF")

    if tesseract_available():
        r = upload("prescription_ocr.png", png_bytes, "image/png", "prescription", patient_headers)
        check(r.status_code == 201, f"OCR fallback: PNG through real Tesseract (got {r.status_code}: {r.text[:200]})")
        check("amoxicillin" in doc_raw_text(r.json()["id"]).lower(), "OCR fallback: Tesseract read the medicine name")
    else:
        print("SKIP: OCR fallback PNG test -- Tesseract binary not installed")

# ---------------------------------------------------------------- 4. unverified queue + confidence
r = client.get("/records/unverified", headers=patient_headers)
check(r.status_code == 200, "list unverified records")
unverified = r.json()
check(len(unverified) >= 4, f"expected at least 4 extracted records, got {len(unverified)}")
check(all(0.0 <= (rec["confidence"] or 0) <= 1.0 for rec in unverified), "all confidences within 0.0-1.0")

fallback_recs = [rec for rec in unverified if rec.get("source_document_id") == fallback_pdf_doc]
check(len(fallback_recs) >= 1, f"OCR fallback produced records ({len(fallback_recs)})")
check(all(rec["record_date"] == "2022-10-12" for rec in fallback_recs),
      f"'12/10/22' read day-first as 2022-10-12 ({sorted({r['record_date'] for r in fallback_recs})})")

if not USE_REAL_GEMINI:
    # only the Gemini-path prescription -- the OCR fallback upload can
    # produce records with the same titles
    confs = {rec["title"]: rec["confidence"] for rec in unverified
             if rec.get("source_document_id") == document_id}
    check(confs.get("Amoxicillin 500mg") == 0.93, "model-reported confidence is used as-is")
    check(confs.get("Paracetamol") == 0.6, "medication missing a dose is capped at 0.6")
    check(confs.get("Mild hypertension") == 1.0, "out-of-range confidence clamped to 1.0")

# 5. Patient verifies each record
for rec in unverified:
    r = client.post(f"/records/{rec['id']}/verify", json={}, headers=patient_headers)
    check(r.status_code == 200 and r.json()["verification_status"] == "patient_verified",
          f"verify {rec['record_type']} record")

# 6. Patient's own timeline shows all verified records
r = client.get(f"/timeline/{patient_id}", headers=patient_headers)
check(r.status_code == 200, "patient views own timeline")
patient_records = r.json()["records"]
check(not [f for f in r.json()["flags"] if f["type"] == "gap"],
      "no 'No record available between…' gap flags (records span 2022-2026)")
check(all(rec.get("logged_at") for rec in patient_records),
      "every record carries the date it was logged in MediPass")
check(len(patient_records) == len(unverified), f"timeline shows {len(unverified)} verified records")

# ---------------------------------------------------------------- 7-10. consent
r = client.get(f"/timeline/{patient_id}", headers=provider_headers)
check(r.status_code == 403, "provider blocked from timeline without consent")

r = client.get("/users/lookup-patient", params={"email": "priya@example.com"}, headers=provider_headers)
check(r.status_code == 200 and r.json()["id"] == patient_id, "provider looks up patient by email")
r = client.get("/users/lookup-patient", params={"email": "nobody@example.com"}, headers=provider_headers)
check(r.status_code == 404, "patient lookup 404s for unknown email")

# Doctor verification: unverified doctors can't add patients
r = client.post("/access-requests", json={"patient_id": patient_id}, headers=provider_headers)
check(r.status_code == 403 and "isn't verified" in r.json()["detail"], "unverified doctor can't request access")
check(client.get("/doctor-verification/me", headers=provider_headers).json()["status"] == "not_submitted",
      "verification status starts as not submitted")
cert = make_pdf(["Karnataka Medical Council", "Registration No. KMC 12345", "Dr. Kumar, MBBS"])
form = {"specialty": "General Physician", "hospital_name": "City Clinic", "registration_number": "KMC 12345",
        "medical_council": "Karnataka Medical Council", "qualification": "MBBS", "registration_year": "2012"}
r = client.post("/doctor-verification", data={**form, "registration_number": "!"}, headers=provider_headers,
                files={"certificate": ("cert.pdf", cert, "application/pdf")})
check(r.status_code == 400, "invalid registration number rejected")
r = client.post("/doctor-verification", data=form, headers=provider_headers)
check(r.status_code == 400 and "certificate" in r.json()["detail"], "certificate upload required")
r = client.post("/doctor-verification", data=form, headers=provider_headers,
                files={"certificate": ("cert.pdf", cert, "application/pdf")})
check(r.status_code == 200 and r.json()["status"] == "pending", "doctor submits credentials -> pending review")
check(client.post("/access-requests", json={"patient_id": patient_id}, headers=provider_headers).status_code == 403,
      "pending doctor still can't add patients")
import review_doctors  # noqa: E402
check(review_doctors.main(["review_doctors.py", "approve", "drkumar@example.com", "Checked NMC register"]) == 0,
      "reviewer approves the doctor")
me = client.get("/doctor-verification/me", headers=provider_headers).json()
check(me["status"] == "verified" and me["hospital_name"] == "City Clinic", "doctor is verified")

r = client.post("/access-requests", json={"patient_id": patient_id}, headers=provider_headers)
check(r.status_code == 201 and r.json()["status"] == "pending", "provider requests access (pending)")
grant_id = r.json()["id"]

r = client.get("/users/badges", headers=patient_headers)
check(r.json()["pending_access_requests"] == 1, "patient badge shows 1 pending access request")

r = client.get("/access-requests/pending", headers=patient_headers)
check(r.status_code == 200 and len(r.json()) == 1, "patient sees pending request")

# Scope names must match the frontend's SCOPE_OPTIONS / timeline.py mapping
SCOPE = ["medications", "allergies", "diagnoses"]
SCOPE_TYPES = {"medication", "allergy", "diagnosis"}
r = client.post(f"/access-requests/{grant_id}/respond",
                json={"approve": True, "scope": SCOPE}, headers=patient_headers)
check(r.status_code == 200 and r.json()["status"] == "approved", "patient approves scoped access")
check(r.json()["patient_name"] == "Priya Sharma", "grant response includes patient name")

r = client.get("/access-requests/for-me", headers=patient_headers)
check(r.status_code == 200 and r.json()[0]["provider_name"] == "Dr. Kumar", "patient lists own grants with provider name")
check(r.json()[0]["provider_verified"] is True and r.json()[0]["provider_hospital"] == "City Clinic",
      "patient sees the doctor is verified, and their hospital")
r = client.get("/access-requests/mine", headers=provider_headers)
check(r.status_code == 200 and r.json()[0]["status"] == "approved", "provider sees approved grant")

r = client.get(f"/timeline/{patient_id}", headers=provider_headers)
check(r.status_code == 200, "provider views timeline after consent")
expected = [rec for rec in patient_records if rec["record_type"] in SCOPE_TYPES]
got_types = {rec["record_type"] for rec in r.json()["records"]}
check(len(expected) > 0 and len(r.json()["records"]) == len(expected),
      f"provider sees exactly the {len(expected)} in-scope records")
check(got_types <= SCOPE_TYPES, f"no out-of-scope record types leaked ({got_types})")

# Gemini down (e.g. daily free-tier quota): AI features must degrade, not 500
gemini_down = RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")
with mock.patch.object(llm, "get_gemini_client", side_effect=gemini_down):
    r = client.get(f"/access-requests/{grant_id}/recommendation", headers=patient_headers)
    check(r.status_code == 200 and r.json()["recommended_scopes"],
          "scope recommendation falls back to rules when Gemini is down")
    r = client.get(f"/timeline/{patient_id}/summary", headers=provider_headers)
    summary = r.json()["summary"]
    check(r.status_code == 200 and "unavailable" in summary and "](#" in summary,
          "timeline summary falls back to a cited factual digest when Gemini is down")
    check(not any(t in summary for t in ("Admission", "Hemoglobin")),
          "fallback summary respects the provider's sharing scope")

# ---------------------------------------------------------------- 11-13. provider records + notifications
r = client.post("/consultations", json={
    "patient_id": patient_id, "record_type": "consultation", "title": "Follow-up consultation",
    "details": {"notes": "Blood pressure stable, continue current medication."}, "record_date": "2026-09-19",
}, headers=provider_headers)
check(r.status_code == 201 and r.json()["source_type"] == "doctor_generated", "provider adds consultation")
consult_id = r.json()["id"]

r = client.get(f"/timeline/{patient_id}", headers=patient_headers)
check(len(r.json()["records"]) == len(patient_records) + 1, "patient timeline gains the provider's record")

r = client.get("/notifications", headers=patient_headers)
check(r.status_code == 200 and len(r.json()) == 1, "patient gets a notification")
notif = r.json()[0]
check(notif["related_record_id"] == consult_id, "notification links to the new record")
check(notif["message"] == "Dr. Kumar added a new consultation record: Follow-up consultation",
      f"notification text is readable ({notif['message']!r})")
check(client.get("/users/badges", headers=patient_headers).json()["unread_notifications"] == 1, "unread badge = 1")
check(client.post(f"/notifications/{notif['id']}/read", headers=provider_headers).status_code == 404,
      "provider cannot mark the patient's notification read")
check(client.post(f"/notifications/{notif['id']}/read", headers=patient_headers).status_code == 200,
      "patient marks notification read")
check(client.get("/users/badges", headers=patient_headers).json()["unread_notifications"] == 0, "unread badge back to 0")

# Conflict detection: document said penicillin allergy; provider logs "no known allergies"
r = client.post("/consultations", json={
    "patient_id": patient_id, "record_type": "allergy", "title": "Allergy check",
    "details": {"text": "no known allergies"}, "record_date": "2026-09-19",
}, headers=provider_headers)
check(r.status_code == 201, "provider logs conflicting allergy info")

r = client.get(f"/timeline/{patient_id}", headers=patient_headers)
conflicts = [f for f in r.json()["flags"] if f["type"] == "conflict"]
check(any("no known allergies" in f["message"] for f in conflicts),
      "allergy contradiction flagged, not silently resolved")

r = client.get("/consultations/mine", headers=provider_headers)
check(r.status_code == 200 and len(r.json()) == 2, "provider dashboard lists their 2 recent records")
check(r.json()[0]["patient_name"] == "Priya Sharma", "recent records include patient name")

# ---------------------------------------------------------------- patient QR -> instant add
r = client.post("/patient-qr", json={"scope": [], "access_days": 7}, headers=patient_headers)
check(r.status_code == 400, "QR code needs at least one thing to share")
r = client.post("/patient-qr", json={"scope": ["medications"], "valid_minutes": 1}, headers=patient_headers)
check(r.status_code == 400, "QR validity below 5 minutes rejected")
check(client.post("/patient-qr", json={"scope": ["medications"]}, headers=provider_headers).status_code == 403,
      "doctors can't create patient QR codes")

r = client.post("/patient-qr", json={"scope": ["allergies", "medications"], "access_days": 7}, headers=patient_headers)
check(r.status_code == 201 and len(r.json()["token"]) >= 40, "patient creates a QR code")
qr_id, qr_token = r.json()["id"], r.json()["token"]
db = SessionLocal()
try:
    row = db.query(models.PatientQRCode).filter(models.PatientQRCode.id == qr_id).first()
    check(row.token_hash != qr_token and len(row.token_hash) == 64, "only a SHA-256 hash of the token is stored")
finally:
    db.close()

check(client.get(f"/timeline/{patient_id}", headers=demo_doctor_headers).status_code == 403,
      "new doctor has no access before scanning")
pending_before = len(client.get("/access-requests/pending", headers=patient_headers).json())
check(client.post("/patient-qr/redeem", json={"code": qr_token}, headers=patient_headers).status_code == 403,
      "patients can't redeem QR codes")
check(client.post("/patient-qr/redeem", json={"code": "not-a-real-code-" + "x" * 30}, headers=demo_doctor_headers).status_code == 404,
      "unknown code rejected")

r = client.post("/patient-qr/redeem", json={"code": f"http://localhost:5173/add-patient/{qr_token}"}, headers=demo_doctor_headers)
check(r.status_code == 200 and r.json()["patient_name"] == "Priya Sharma" and not r.json()["already_had_access"],
      "doctor scans the QR (full link) -> patient added instantly")
check(sorted(r.json()["scope"]) == ["allergies", "medications"], "grant carries the scope the patient chose")
r = client.get(f"/timeline/{patient_id}", headers=demo_doctor_headers)
check(r.status_code == 200, "doctor can open the patient's timeline immediately")
check({x["record_type"] for x in r.json()["records"]} <= {"allergy", "medication"}, "QR scope enforced on the timeline")
check(len(client.get("/access-requests/pending", headers=patient_headers).json()) == pending_before,
      "no access request was created for the patient to approve")
mine = client.get("/access-requests/mine", headers=demo_doctor_headers).json()
check(any(g["patient_id"] == patient_id and g["status"] == "approved" for g in mine),
      "patient appears in the doctor's list as approved")

r = client.post("/patient-qr/redeem", json={"code": qr_token}, headers=demo_doctor_headers)
check(r.status_code == 410, "a QR code only works once")
check(client.get(f"/patient-qr/{qr_id}", headers=patient_headers).json()["used_by_name"] == "Demo Doctor",
      "patient's screen can see who scanned it")
notes = [n["message"] for n in client.get("/notifications", headers=patient_headers).json()]
check(any("scanned your QR code" in m for m in notes), "patient is informed (no approval asked)")

# A new code cancels the previous unused one; cancelled/expired codes fail
old = client.post("/patient-qr", json={"scope": ["labs"]}, headers=patient_headers).json()
new = client.post("/patient-qr", json={"scope": ["labs"]}, headers=patient_headers).json()
check(client.post("/patient-qr/redeem", json={"code": old["token"]}, headers=demo_doctor_headers).status_code == 410,
      "generating a new code cancels the old unused one")
client.post(f"/patient-qr/{new['id']}/revoke", headers=patient_headers)
check(client.post("/patient-qr/redeem", json={"code": new["token"]}, headers=demo_doctor_headers).status_code == 410,
      "patient-cancelled code rejected")
expiring = client.post("/patient-qr", json={"scope": ["labs"]}, headers=patient_headers).json()
db = SessionLocal()
try:
    row = db.query(models.PatientQRCode).filter(models.PatientQRCode.id == expiring["id"]).first()
    row.expires_at = __import__("datetime").datetime.utcnow() - __import__("datetime").timedelta(seconds=1)
    db.commit()
finally:
    db.close()
check(client.post("/patient-qr/redeem", json={"code": expiring["token"]}, headers=demo_doctor_headers).status_code == 410,
      "expired code rejected")

# Doctor who already has active access: told the patient already exists, nothing changes
grant_before = [g for g in client.get("/access-requests/for-me", headers=patient_headers).json()
                if g["provider_name"] == "Dr. Kumar"][0]
again = client.post("/patient-qr", json={"scope": ["full_history"], "access_days": 90}, headers=patient_headers).json()
r = client.post("/patient-qr/redeem", json={"code": again["token"]}, headers=provider_headers)
check(r.status_code == 200 and r.json()["already_had_access"] and r.json()["grant_id"] == grant_id,
      "existing active patient: doctor told they're already a patient")
grant_after = [g for g in client.get("/access-requests/for-me", headers=patient_headers).json()
               if g["provider_name"] == "Dr. Kumar"]
check(len(grant_after) == 1 and grant_after[0]["scope"] == grant_before["scope"]
      and grant_after[0]["expires_at"] == grant_before["expires_at"]
      and grant_after[0]["responded_at"] == grant_before["responded_at"],
      "existing access left untouched (scope, expiry and approval time unchanged)")
check(r.json()["scope"] == grant_before["scope"], "doctor is shown the current sharing, not the QR's")
check(client.get(f"/patient-qr/{again['id']}", headers=patient_headers).json()["outcome"] == "already_patient",
      "patient's screen shows 'already their patient'")
check(any("already their patient" in n["message"] for n in client.get("/notifications", headers=patient_headers).json()),
      "patient notified that nothing changed")
check(client.post("/patient-qr/redeem", json={"code": again["token"]}, headers=provider_headers).status_code == 410,
      "the code is still used up")

# ---------------------------------------------------------------- consultation note <-> prescription links
def upload_rx(name, doctor, when, medicine):
    fake_gemini.next_payload = {
        "document_type": "prescription", "prescribing_doctor": doctor, "hospital_name": "City Clinic",
        "records": [{"record_type": "medication", "title": f"{medicine} 5mg",
                     "details": {"medicine": medicine, "dose": "5mg"}, "confidence": 0.9, "record_date": when}],
    }
    r = upload(name, make_test_prescription_png(), "image/png", "prescription", patient_headers)
    check(r.status_code == 201, f"upload prescription {name}")
    return r.json()["id"]


def links_by_note():
    return {l["consultation"]["id"]: l for l in client.get(f"/links/patient/{patient_id}", headers=patient_headers).json()}


def add_note(title, when, notes):
    r = client.post("/consultations", json={"patient_id": patient_id, "record_type": "consultation", "title": title,
                                           "details": {"notes": notes}, "record_date": when}, headers=provider_headers)
    check(r.status_code == 201, f"Dr. Kumar adds note '{title}'")
    return r.json()["id"]


# The earlier note (consult_id) has no Dr. Kumar prescription yet -> unmatched (via backfill)
lk = links_by_note()[consult_id]
check(lk["status"] == "unmatched" and "No prescription from Dr. Kumar" in lk["match_reason"],
      "note with no prescription from its author: unmatched, with a clear reason")

# Prescription uploaded AFTER the note -> links automatically
rx_kumar = upload_rx("rx_kumar.png", "Dr. Kumar", "2026-09-15", "Amlodipine")
lk = links_by_note()[consult_id]
check(lk["status"] == "linked" and lk["document"]["id"] == rx_kumar and lk["method"] == "auto",
      "prescription uploaded later is linked to the waiting note")
check("prescription uploaded" in lk["process"] and lk["ref"].startswith("L-"), "link records which process made it")

rx_mehta = upload_rx("rx_mehta.png", "Dr. R. Mehta", "2026-09-16", "Cetirizine")
check(links_by_note()[consult_id]["document"]["hospital"] == "City Clinic"
      and "same hospital (City Clinic)" in links_by_note()[consult_id]["match_reason"],
      "prescription's hospital is extracted and matched to the doctor's affiliation")
note_amlo = add_note("BP review", "2026-09-16", "BP better on amlodipine, continue.")
lk = links_by_note()[note_amlo]
check(lk["status"] == "linked" and lk["document"]["id"] == rx_kumar,
      "new note links to its author's prescription, not another doctor's")
check("consultation added" in lk["process"], "trigger recorded: consultation added")

# Two equally good prescriptions from the same doctor -> ambiguous, needs a person
rx_june_a = upload_rx("rx_june_a.png", "Dr Kumar", "2026-06-01", "Metformin")
rx_june_b = upload_rx("rx_june_b.png", "Dr. Kumar", "2026-06-01", "Atorvastatin")
note_june = add_note("June check", "2026-06-01", "Routine visit.")
lk = links_by_note()[note_june]
check(lk["status"] == "ambiguous" and {c["id"] for c in lk["candidates"]} >= {rx_june_a, rx_june_b},
      "two equally likely prescriptions -> ambiguous with both as candidates")

# ... but consultation context breaks the tie
note_metf = add_note("Sugar review", "2026-06-01", "Continue metformin, recheck HbA1c.")
lk = links_by_note()[note_metf]
check(lk["status"] == "linked" and lk["document"]["id"] == rx_june_a,
      "note mentioning the medicine picks the matching prescription")

cands = client.get(f"/links/consultation/{note_june}/candidates", headers=provider_headers).json()
check({c["id"] for c in cands if c["eligible"]} == {rx_kumar, rx_june_a, rx_june_b}
      and not [c for c in cands if c["id"] == rx_mehta][0]["eligible"],
      "candidates: author's prescriptions eligible, other doctor's not")

# Manual override: authorization, reason, and it sticks
check(client.post(f"/links/consultation/{note_june}/override", json={"document_id": rx_june_b, "reason": "x"},
                  headers=provider_headers).status_code == 400, "override needs a real reason")
check(client.post(f"/links/consultation/{note_june}/override",
                  json={"document_id": rx_june_b, "reason": "Discussed statin at this visit"},
                  headers=demo_doctor_headers).status_code in (403,), "only the note's author (or patient) can override")
check(client.post(f"/links/consultation/{note_june}/override",
                  json={"document_id": rx_mehta, "reason": "wrong on purpose"},
                  headers=provider_headers).status_code == 200, "author may link any of the patient's prescriptions")
r = client.post(f"/links/consultation/{note_june}/override",
                json={"document_id": rx_june_b, "reason": "Discussed statin at this visit"}, headers=provider_headers)
check(r.status_code == 200 and r.json()["method"] == "manual" and r.json()["document"]["id"] == rx_june_b
      and r.json()["override_reason"] == "Discussed statin at this visit" and r.json()["overridden_by"] == "Dr. Kumar",
      "manual override saved with reason and who did it")
upload_rx("rx_june_c.png", "Dr. Kumar", "2026-06-01", "Aspirin")
check(links_by_note()[note_june]["document"]["id"] == rx_june_b, "auto-linker never overwrites a manual link")
r = client.post(f"/links/consultation/{note_june}/override",
                json={"document_id": None, "reason": "Not related to any prescription"}, headers=patient_headers)
check(r.status_code == 200 and r.json()["status"] == "unmatched" and r.json()["method"] == "manual",
      "patient can unlink with a reason")
check(client.post(f"/links/consultation/{note_june}/override", json={"document_id": "nope", "reason": "bad doc id"},
                  headers=patient_headers).status_code == 400, "can't link a document that isn't this patient's prescription")

# Patient confirmation: proposals await the patient; accepted links are final
check(client.get("/users/badges", headers=patient_headers).json()["pending_links"] >= 1,
      "badge counts links waiting for the patient")
lk = links_by_note()[note_amlo]
check(lk["status"] == "linked" and lk["awaiting_patient"], "automatic link is a proposal awaiting the patient")
check(client.post(f"/links/{lk['id']}/accept", headers=provider_headers).status_code == 403,
      "only the patient can accept a link")
r = client.post(f"/links/{lk['id']}/accept", headers=patient_headers)
check(r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["confirmed_at"],
      "patient accepts the link")
check(client.post(f"/links/consultation/{note_amlo}/override", json={"document_id": None, "reason": "try to unlink"},
                  headers=patient_headers).status_code == 409, "confirmed link can't be changed by the patient")
check(client.post(f"/links/consultation/{note_amlo}/override", json={"document_id": rx_june_a, "reason": "try to relink"},
                  headers=provider_headers).status_code == 409, "confirmed link can't be changed by the doctor")
check(client.post(f"/links/{lk['id']}/reject", headers=patient_headers).status_code == 409,
      "confirmed link can't be rejected afterwards")
check(client.delete(f"/records/{note_amlo}", headers=patient_headers).status_code == 409,
      "note in a confirmed link can't be removed")
upload_rx("rx_kumar_2.png", "Dr. Kumar", "2026-09-16", "Amlodipine")
check(links_by_note()[note_amlo]["document"]["id"] == rx_kumar and links_by_note()[note_amlo]["status"] == "confirmed",
      "auto-linker leaves a confirmed link alone")

lk = links_by_note()[note_metf]
r = client.post(f"/links/{lk['id']}/reject", json={"reason": "That was a different visit"}, headers=patient_headers)
check(r.status_code == 200 and r.json()["status"] == "unmatched" and r.json()["override_reason"] == "That was a different visit",
      "patient rejects a proposed link with a reason")
upload_rx("rx_june_d.png", "Dr. Kumar", "2026-06-01", "Metformin")
check(links_by_note()[note_metf]["status"] == "unmatched", "a rejected link isn't re-proposed automatically")

acts = [e["action"] for e in client.get("/audit-log", headers=patient_headers).json()]
check({"record_linked", "record_link_needs_review", "record_link_overridden",
       "record_link_confirmed", "record_link_rejected"} <= set(acts), "link events audited")
entry = [e for e in client.get("/audit-log", headers=patient_headers).json() if e["action"] == "record_link_overridden"][0]
check(entry["actor_name"] in ("Dr. Kumar", "Priya Sharma") and entry["actor_role"] in ("provider", "patient"),
      "activity log says who did it")

# ---------------------------------------------------------------- voice dictation without AI
with mock.patch.object(llm, "get_gemini_client", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED. quota")):
    r = client.post("/consultations/voice-structure",
                    json={"transcript": "prescribed amoxicillin 500 mg twice daily, follow up after one week"},
                    headers=provider_headers)
v = r.json()
check(r.status_code == 200 and v["record_type"] == "medication" and v["details"].get("medicine") == "Amoxicillin"
      and v["details"].get("dose") == "500 mg" and v.get("structured_by") == "rules" and v["warnings"],
      "voice dictation is still structured (rule-based) when every Gemini model is out of quota")

# ---------------------------------------------------------------- 13b. day counts (treatment courses, follow-ups)
from datetime import date as _date  # noqa: E402
from app import durations  # noqa: E402

c = durations.medication_course({"notes": "x 10 days"}, _date(2025, 5, 31))
check(c["duration_days"] == 10 and c["end_date"] == "2025-06-09", f"10-day course from 31 May ends 9 Jun ({c})")
c = durations.medication_course({"timing": "1-0-1 for 5 days"}, _date(2024, 2, 26))
check(c["end_date"] == "2024-03-01", f"5 days from 26 Feb 2024 crosses the leap day ({c})")
c = durations.medication_course({"duration": "1 month"}, _date(2024, 1, 31))
check((c["end_date"], c["duration_days"]) == ("2024-02-29", 30), f"1 month from 31 Jan 2024 (leap year) ({c})")
c = durations.medication_course({"duration": "1 month"}, _date(2023, 1, 31))
check((c["end_date"], c["duration_days"]) == ("2023-02-28", 29), f"1 month from 31 Jan 2023 ({c})")
c = durations.medication_course({"duration": "1 year"}, _date(2024, 2, 29))
check(c["duration_days"] == 366, f"1 year from 29 Feb 2024 is 366 days ({c})")
for text, days in [("x10d", 10), ("2/52", 14), ("5/7", 5), ("for one week", 7), ("Tab 20mg 1-0-0 x 2 wks", 14)]:
    c = durations.medication_course({"timing": text}, _date(2025, 1, 1))
    check(c and c["duration_days"] == days, f"duration '{text}' = {days} days ({c})")
check(durations.medication_course({"timing": "1-0-1", "dose": "0.25mg"}, _date(2025, 1, 1)) is None,
      "no duration written -> no course")
check(durations.medication_course({"timing": "SOS"}, _date(2025, 1, 1))["duration"] == "as needed", "SOS = as needed")
check(durations.follow_up_due("Review after 2 weeks", _date(2025, 5, 31)) == _date(2025, 6, 14), "review after 2 weeks")
check(durations.follow_up_due("Follow up on 5/7/25", _date(2025, 5, 31)) == _date(2025, 7, 5),
      "follow-up date read day-first")

if not USE_REAL_GEMINI:
    fake_gemini.next_payload = {
        "document_type": "prescription",
        "prescribing_doctor": "Dr. Kumar",
        "records": [
            {"record_type": "medication", "title": "Cetirizine 10mg",
             "details": {"medicine": "Cetirizine", "dose": "10mg", "timing": "0-0-1", "duration": "x 5 days"},
             "confidence": 0.95, "record_date": "2024-02-26"},
            {"record_type": "medication", "title": "Azithromycin 500mg",
             "details": {"medicine": "Azithromycin", "dose": "500mg", "timing": "1-0-0 for 3 days"},
             "confidence": 0.95, "record_date": "2024-02-26"},
            # no timing -> one of four checks fails
            {"record_type": "medication", "title": "Vitamin D3",
             "details": {"medicine": "Vitamin D3", "dose": "60000 IU"}, "confidence": 0.9, "record_date": "2024-02-26"},
        ],
    }
    r = upload("rx_days.png", png_bytes, "image/png", "prescription", patient_headers)
    check(r.status_code == 201, f"prescription with durations uploaded ({r.status_code})")
    days_doc = r.json()["id"]
    recs = {x["title"]: x for x in client.get("/records/unverified", headers=patient_headers).json()
            if x["source_document_id"] == days_doc}
    cet, azi, vit = recs["Cetirizine 10mg"], recs["Azithromycin 500mg"], recs["Vitamin D3"]
    check(cet["course"] == {"duration": "5 days", "duration_days": 5, "start_date": "2024-02-26",
                            "end_date": "2024-03-01", "ongoing": False},
          f"course from the written duration ({cet['course']})")
    check(azi["details"]["duration"] == "3 days" and azi["course"]["end_date"] == "2024-02-28",
          f"duration pulled out of the timing text ({azi['details'].get('duration')}, {azi['course']})")
    check(cet["confidence"] == 0.95 and cet["details"]["confidence_basis"]["checks_passed"] == 4,
          "complete medication keeps the model's confidence")
    check(vit["confidence"] == round(0.9 * 0.875, 3) and vit["details"]["confidence_basis"]["missing"] == ["timing given"],
          f"missing timing lowers confidence and says why ({vit['confidence']}, {vit['details'].get('confidence_basis')})")
    # patient corrects the date -> day counts follow
    r = client.post(f"/records/{cet['id']}/verify", json={"corrected_record_date": "2023-02-26"}, headers=patient_headers)
    check(r.json()["course"]["end_date"] == "2023-03-02", f"course end moves with a corrected date ({r.json()['course']})")
    for x in (azi, vit):
        client.delete(f"/records/{x['id']}", headers=patient_headers)

    # no date written on the document -> the "date on document" check fails
    fake_gemini.next_payload = {"document_type": "prescription", "records": [
        {"record_type": "diagnosis", "title": "Allergic rhinitis", "details": {}, "confidence": 0.9}]}
    r = upload("rx_nodate.png", png_bytes, "image/png", "prescription", patient_headers)
    rec = [x for x in client.get("/records/unverified", headers=patient_headers).json()
           if x["source_document_id"] == r.json()["id"]][0]
    check(rec["confidence"] == 0.675 and rec["details"]["confidence_basis"]["missing"] == ["date on document"],
          f"no date on the document lowers confidence ({rec['confidence']})")
    client.delete(f"/records/{rec['id']}", headers=patient_headers)

# ---------------------------------------------------------------- 13c. doctor verification document
vdoc = client.get("/doctor-verification/document", headers=provider_headers).json()
check(vdoc["status"] == "verified" and vdoc["compliance"]["overall"] == "Compliant",
      f"verified doctor's document says Compliant ({vdoc['compliance']})")
check(vdoc["credentials"]["registration_number"] == "KMC 12345" and vdoc["credentials"]["license_status"] == "Verified",
      "document lists the licence details")
check(vdoc["experience"]["years"] == _date.today().year - 2012, "years of experience from the registration year")
check(vdoc["verification"]["reviewer"] and vdoc["verification"]["reviewed_at"], "document shows who reviewed it and when")
r = client.post("/doctor-verification", headers=provider_headers, data={
    **form, "education": json.dumps([{"degree": "MBBS", "institution": "", "year": 2010}])})
check(r.status_code == 400 and "institution" in r.json()["detail"], "education entry needs an institution")
r = client.post("/doctor-verification", headers=provider_headers, data={
    **form, "practice_start_year": "2010",
    "education": json.dumps([{"degree": "MBBS", "institution": "Bangalore Medical College", "year": 2010},
                             {"degree": "", "institution": "", "year": ""}]),
    "affiliations": json.dumps(["City Clinic", "St. John's Hospital"])})
check(r.status_code == 200 and r.json()["status"] == "pending", "updated profile goes back to review")
check(r.json()["education"] == [{"degree": "MBBS", "institution": "Bangalore Medical College", "year": 2010}],
      "empty education rows are dropped")
check(r.json()["affiliations"] == ["St. John's Hospital"], "primary hospital isn't repeated in other affiliations")
vdoc = client.get("/doctor-verification/document", headers=provider_headers).json()
check(vdoc["compliance"]["overall"] == "Pending review", "document shows Pending review while re-checked")
check(review_doctors.main(["review_doctors.py", "approve", "drkumar@example.com", "Re-checked",
                           "--by", "Dr. A. Reviewer"]) == 0,
      "reviewer approves again, with their name")
vdoc = client.get("/doctor-verification/document", headers=provider_headers).json()
check(vdoc["verification"]["reviewer"] == "Dr. A. Reviewer" and vdoc["compliance"]["overall"] == "Compliant",
      "approval authority recorded on the document")
check(vdoc["experience"] == {"since": 2010, "since_basis": "practice start", "years": _date.today().year - 2010},
      f"experience counts from the practice start year ({vdoc['experience']})")
check(all(c["passed"] for c in vdoc["compliance"]["checks"]), "every compliance check met")


# ---------------------------------------------------------------- 13d. Active Patients list
def my_patients():
    return client.get("/provider/patients", headers=provider_headers).json()


def priya_row():
    return next(p for p in my_patients()["active"] if p["patient_id"] == patient_id)


data = my_patients()
check(data["total_active"] == len(data["active"]) >= 1 and data["generated_at"], "active patients list with timestamp")
check(sum(data["counts"].values()) == data["total_active"], "status counts add up to the total")
row = priya_row()
check(row["status"] in ("new", "ongoing", "critical", "follow_up") and row["status_reason"],
      "every patient has a status and reason")
check(row["days_under_care"] >= 0 and row["consultations"] >= 1 and row["last_visit"], "metrics filled in")
today = _date.today()
r = client.post("/consultations", headers=provider_headers, json={
    "patient_id": patient_id, "record_type": "consultation", "title": "Check-up", "record_date": today.isoformat(),
    "details": {"text": "Stable.", "follow_up": f"Follow up on {today.strftime('%d/%m/%Y')} with reports"}})
check(r.status_code == 201, "doctor adds a note with a follow-up date")
row = priya_row()
check(row["status"] == "follow_up" and row["follow_up_due"] == today.isoformat() and row["days_since_last_visit"] == 0,
      f"follow-up due today -> Follow-up required ({row['status']}, {row['status_reason']})")
r = client.post("/consultations", headers=provider_headers, json={
    "patient_id": patient_id, "record_type": "consultation", "title": "Chest pain", "record_date": today.isoformat(),
    "details": {"text": "Urgent referral to cardiology, rule out myocardial infarction."}})
row = priya_row()
check(row["status"] == "critical" and "Urgent" in row["status_reason"], f"urgent finding -> Critical ({row['status_reason']})")
r = client.put(f"/provider/patients/{patient_id}/status", headers=provider_headers,
               json={"status": "ongoing", "note": "Seen by cardiology"})
row = priya_row()
check(r.status_code == 200 and row["status"] == "ongoing" and row["status_set_by_doctor"], "doctor sets the status by hand")
check(client.put(f"/provider/patients/{patient_id}/status", headers=provider_headers,
                 json={"status": "bogus"}).status_code == 400, "unknown status rejected")
client.put(f"/provider/patients/{patient_id}/status", headers=provider_headers, json={"status": None})
check(priya_row()["status"] == "critical" and not priya_row()["status_set_by_doctor"], "back to the automatic status")
check(client.get("/provider/patients", headers=patient_headers).status_code == 403, "patients can't call the doctor's list")

# ---------------------------------------------------------------- 13e. runaway X-ray "view" from the model
from app.imaging import normalize_view  # noqa: E402

check(normalize_view("PA") == "PA" and normalize_view("PA and lateral") == "PA / lateral", "known projections kept")
check(normalize_view("PA_or_AP_unknown_exact_projection_but_full_chest_visible") == "",
      "an unsure / runaway projection is dropped")
if not USE_REAL_GEMINI:
    runaway = "PA_or_AP_unknown_exact_projection_" + "and_more_words_" * 400
    fake_gemini.next_payload = {"document_type": "lab_report", "records": [
        {"record_type": "lab_result", "title": "Chest radiograph",
         "details": {"modality": "xray", "body_part": "chest", "view": runaway, "text": "Chest X-ray. " + "x" * 5000},
         "confidence": 0.95}]}
    r = upload("runaway_xray.png", make_blank_png(), "image/png", "lab_report", patient_headers)
    rec = [x for x in client.get("/records/unverified", headers=patient_headers).json()
           if x["source_document_id"] == r.json()["id"]][0]
    check("view" not in rec["details"] and len(rec["details"]["text"]) <= 1501,
          f"runaway view dropped and long text capped ({rec['details'].get('view', '')[:40]}, {len(rec['details']['text'])})")
    # a record saved before the fix still shows cleanly
    db = SessionLocal()
    try:
        row = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == rec["id"]).first()
        row.details = json.dumps({**json.loads(row.details), "view": runaway})
        db.commit()
    finally:
        db.close()
    rec = [x for x in client.get("/records/unverified", headers=patient_headers).json() if x["id"] == rec["id"]][0]
    check("view" not in rec["details"], "old record with a runaway view is cleaned when read")
    check(rec["details"]["text"] == "Chest radiograph (X-ray) showing the lungs, heart shadow, mediastinum and thoracic cage.",
          f"runaway description replaced by the standard one ({rec['details']['text'][:60]})")
    db = SessionLocal()
    try:
        row = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == rec["id"]).first()
        row.details = json.dumps({**json.loads(row.details), "text": "X-ray image uploaded.", "view": "PA"})
        db.commit()
    finally:
        db.close()
    rec = [x for x in client.get("/records/unverified", headers=patient_headers).json() if x["id"] == rec["id"]][0]
    check(rec["details"]["text"].startswith("Chest radiograph (X-ray, PA view) showing the lungs"),
          f"old 'X-ray image uploaded.' shown as a description ({rec['details']['text']})")
    client.delete(f"/records/{rec['id']}", headers=patient_headers)

# ---------------------------------------------------------------- 13f. duplicate uploads / records
r = upload("prescription_again.png", png_bytes, "image/png", "prescription", patient_headers, allow_duplicate=False)
check(r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_upload" and r.json()["detail"]["document_id"],
      f"identical file re-uploaded -> warned before any AI call ({r.status_code})")
if not USE_REAL_GEMINI:
    fake_gemini.next_payload = FAKE_PRESCRIPTION
    r = upload("prescription_again.png", png_bytes, "image/png", "prescription", patient_headers, allow_duplicate=False)
    check(r.status_code == 409, "still warned the second time")
    r = upload("prescription_again.png", png_bytes, "image/png", "prescription", patient_headers)
    check(r.status_code == 201, "'Upload anyway' goes through")
    again_doc = r.json()["id"]
    again = [x for x in client.get("/records/unverified", headers=patient_headers).json()
             if x["source_document_id"] == again_doc]
    amox = next(x for x in again if x["title"] == "Amoxicillin 500mg")
    check(amox["duplicate_of"] and amox["duplicate_of"]["title"] == "Amoxicillin 500mg",
          f"repeated entry flagged as a duplicate of the timeline record ({amox['duplicate_of']})")
    for x in again:
        client.delete(f"/records/{x['id']}", headers=patient_headers)

from app import duplicates as dup_mod  # noqa: E402


class _R:  # minimal stand-in for MedicalRecord
    def __init__(self, id, title, details, doc, rtype=models.RecordType.medication, date="2025-08-21"):
        self.id, self.title, self.details, self.source_document_id = id, title, json.dumps(details), doc
        self.record_type, self.record_date = rtype, date


check(dup_mod.is_duplicate(_R("a", "Zocalm 5mg SOS", {}, "d1"), _R("b", "Tab. Zolcalm 5mg", {"medicine": "Tab. Zolcalm", "dose": "5mg"}, "d2")),
      "spelling slip in a medicine name still counts as a duplicate")
check(not dup_mod.is_duplicate(_R("a", "Ecosprin 70mg", {}, "d1"), _R("b", "Ecosprin 40mg", {"dose": "40mg"}, "d2")),
      "different doses are not duplicates")
check(not dup_mod.is_duplicate(_R("a", "Paracetamol 500mg", {}, "d1"), _R("b", "Paracetamol 500mg", {}, "d1")),
      "two entries on the same prescription are not duplicates")
check(not dup_mod.is_duplicate(_R("a", "Paracetamol 500mg", {}, "d1"), _R("b", "Paracetamol 500mg", {}, "d2", date="2025-09-01")),
      "the same medicine prescribed on another day is not a duplicate")
check(not dup_mod.is_duplicate(
    _R("a", "Note from prescription", {"text": "PSYCHIATRIC CLINIC"}, "d1", models.RecordType.consultation),
    _R("b", "Note from prescription", {"text": "berqat Feapin 40"}, "d2", models.RecordType.consultation)),
      "generic titles with different text are not duplicates")

import find_duplicates  # noqa: E402

before = client.get(f"/timeline/{patient_id}", headers=patient_headers).json()["records"]
check(find_duplicates.main(["find_duplicates.py", "--email", "priya@example.com"]) == 0, "duplicate finder runs")
after = client.get(f"/timeline/{patient_id}", headers=patient_headers).json()["records"]
check(len(before) == len(after), "listing duplicates changes nothing")

# ---------------------------------------------------------------- 13g. patient sets the prescribing doctor / hospital
r = client.patch(f"/documents/{document_id}/prescriber", headers=patient_headers,
                 json={"doctor_name": "Anita Rao", "hospital_name": "Sunrise Clinic"})
check(r.status_code == 200 and r.json()["doctor_name"] == "Dr. Anita Rao", f"patient sets the prescriber ({r.text[:120]})")
recs = [x for x in client.get(f"/timeline/{patient_id}", headers=patient_headers).json()["records"]
        if x["source_document_id"] == document_id]
check(recs and all(x["details"].get("doctor_name") == "Dr. Anita Rao" and x["details"].get("hospital_name") == "Sunrise Clinic"
                   for x in recs), "every entry from that prescription carries the doctor and hospital")
check(client.patch(f"/documents/{document_id}/prescriber", headers=provider_headers,
                   json={"doctor_name": "Dr. X Y"}).status_code == 403, "doctors can't edit a patient's prescription")
check(client.patch(f"/documents/{fallback_pdf_doc}/prescriber", headers=patient_headers,
                   json={"doctor_name": "Dr. Anita Rao"}).status_code == 400, "lab reports have no prescriber")
check(client.patch(f"/documents/{document_id}/prescriber", headers=patient_headers,
                   json={"doctor_name": "Dr"}).status_code == 400, "too-short doctor name rejected")
db = SessionLocal()
try:
    locked_doc = db.query(models.RecordLink).filter(models.RecordLink.status == "confirmed").first().document_id
finally:
    db.close()
r = client.patch(f"/documents/{locked_doc}/prescriber", headers=patient_headers, json={"doctor_name": "Dr. Someone Else"})
check(r.status_code == 409, "prescriber locked once a link to the prescription is confirmed")
actions = [e["action"] for e in client.get("/audit-log", headers=patient_headers).json()]
check("prescriber_edited" in actions, "prescriber edit is audited")

if not USE_REAL_GEMINI:
    # a handwritten prescription with no readable doctor can't link ...
    fake_gemini.next_payload = {"document_type": "prescription", "records": [
        {"record_type": "medication", "title": "Montelukast 10mg",
         "details": {"medicine": "Montelukast", "dose": "10mg", "timing": "0-0-1"},
         "confidence": 0.9, "record_date": "2026-03-03"}]}
    r = upload("handwritten.png", make_blank_png(), "image/png", "prescription", patient_headers)
    nodoc = r.json()["id"]
    for x in client.get("/records/unverified", headers=patient_headers).json():
        if x["source_document_id"] == nodoc:
            client.post(f"/records/{x['id']}/verify", json={}, headers=patient_headers)
    r = client.post("/consultations", headers=provider_headers, json={
        "patient_id": patient_id, "record_type": "consultation", "title": "Asthma review", "record_date": "2026-03-03",
        "details": {"text": "Wheeze better on montelukast."}})
    note_id = r.json()["id"]

    def note_link():
        return next(l for l in client.get(f"/links/patient/{patient_id}", headers=patient_headers).json()
                    if l["consultation"]["id"] == note_id)

    first = note_link()
    check((first.get("document") or {}).get("id") != nodoc,
          f"no doctor on the prescription -> the note can't link to it ({first['status']})")
    # ... until the patient says who wrote it
    client.patch(f"/documents/{nodoc}/prescriber", headers=patient_headers, json={"doctor_name": "Dr. Kumar"})
    link = note_link()
    check(link["status"] == "linked" and link["document"]["id"] == nodoc,
          f"after the patient names the doctor, the note links to it ({link['status']}: {link.get('match_reason')})")
    check(link["document"]["items"] == [{"name": "Montelukast", "dose": "10mg", "timing": "0-0-1",
                                         "instructions": "", "course": ""}],
          f"the link carries what the prescription says, for showing in place ({link['document'].get('items')})")
    check(link["consultation"]["text"] == "Wheeze better on montelukast." and link["consultation"]["author_hospital"] == "City Clinic",
          f"the link carries the doctor's consultation for the patient ({link['consultation']})")
    as_author = next(l for l in client.get(f"/links/patient/{patient_id}", headers=provider_headers).json()
                     if l["consultation"]["id"] == note_id)
    check(as_author["consultation"]["text"] == "Wheeze better on montelukast.", "the note's author sees its content too")

# ---------------------------------------------------------------- 13h. verification email: failures surface, resend
from app import email_utils  # noqa: E402

r = client.post("/auth/register", json={"email": "mailok@example.com", "password": "pw12345",
                                        "full_name": "Mail Ok", "role": "patient"})
check(r.status_code == 201 and r.json()["verification_email_sent"] is True, "register reports the email went out")
with mock.patch.object(email_utils, "send_email", return_value=False):
    r = client.post("/auth/register", json={"email": "mailfail@example.com", "password": "pw12345",
                                            "full_name": "Mail Fail", "role": "patient"})
    check(r.status_code == 201 and r.json()["verification_email_sent"] is False,
          "register says so when the verification email couldn't be sent")
    r = client.post("/auth/resend-verification", json={"email": "mailfail@example.com"})
    check(r.status_code == 502, "resend reports a failed send")
r = client.post("/auth/resend-verification", json={"email": "mailfail@example.com"})
check(r.status_code == 429, "resend is rate limited (one a minute)")
r = client.post("/auth/resend-verification", json={"email": "nobody-here@example.com"})
check(r.status_code == 200, "unknown email gets the same generic answer (no account enumeration)")
sent = []
with mock.patch.object(email_utils, "send_email", side_effect=lambda to, subj, html, text="": sent.append((to, html, text)) or True):
    r = client.post("/auth/resend-verification", json={"email": "mailok@example.com"})
check(r.status_code == 200 and sent and "/verify-email?token=" in sent[0][2], "resend sends the link, with a plain-text part")
db = SessionLocal()
try:
    tok = db.query(models.User).filter(models.User.email == "mailok@example.com").first().verification_token
finally:
    db.close()
check(tok in sent[0][2], "the resent link is the account's current token")

# ---------------------------------------------------------------- 13i. registering again before verifying
r = client.post("/auth/register", json={"email": "again@example.com", "password": "pw12345",
                                        "full_name": "First Try", "role": "provider"})
first_id = r.json()["id"]
r = client.post("/auth/register", json={"email": "again@example.com", "password": "newpw678",
                                        "full_name": "Second Try", "role": "patient"})
check(r.status_code == 201 and r.json()["id"] == first_id and r.json()["full_name"] == "Second Try"
      and r.json()["role"] == "patient" and r.json()["verification_email_sent"] is True,
      f"unverified, unused account: signing up again restarts it ({r.status_code} {r.text[:120]})")
db = SessionLocal()
try:
    u = db.query(models.User).filter(models.User.email == "again@example.com").first()
    check(db.query(models.PatientProfile).filter(models.PatientProfile.user_id == u.id).count() == 1
          and db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == u.id).count() == 0,
          "role switched cleanly (one profile, the right kind)")
    token = u.verification_token
finally:
    db.close()
check(client.post("/auth/verify-email", json={"token": token}).status_code == 200, "the new link verifies it")
r = client.post("/auth/login", data={"username": "again@example.com", "password": "newpw678"})
check(r.status_code == 200, "logs in with the new password")
r = client.post("/auth/register", json={"email": "again@example.com", "password": "x1234567",
                                        "full_name": "Hijack", "role": "patient"})
check(r.status_code == 400 and "already registered" in r.json()["detail"], "a verified account can't be registered again")

# unverified but already in use -> never overwritten, link resent
r = client.post("/auth/register", json={"email": "inuse@example.com", "password": "pw12345",
                                        "full_name": "In Use", "role": "provider"})
db = SessionLocal()
try:
    db.add(models.DoctorCredential(provider_id=r.json()["id"], registration_number="KMC 1", medical_council="KMC",
                                   qualification="MBBS", status="pending"))
    db.commit()
finally:
    db.close()
r = client.post("/auth/register", json={"email": "inuse@example.com", "password": "other999",
                                        "full_name": "Someone Else", "role": "patient"})
check(r.status_code == 409 and r.json()["detail"]["code"] == "unverified_exists" and r.json()["detail"]["email_sent"] is True,
      "unverified account with data isn't overwritten; the link is resent")
db = SessionLocal()
try:
    check(db.query(models.User).filter(models.User.email == "inuse@example.com").first().full_name == "In Use",
          "its details are unchanged")
finally:
    db.close()

# ---------------------------------------------------------------- 13j. reviewer screen (approve doctors in the app)
os.environ.pop("MEDIPASS_REVIEWER_EMAILS", None)
check(client.get("/reviewer/me", headers=patient_headers).json() == {"is_reviewer": False}, "nobody is a reviewer by default")
check(client.get("/reviewer/doctors", headers=patient_headers).status_code == 403, "non-reviewers can't list doctors")

r = client.post("/auth/register", json={"email": "revdoc@example.com", "password": "pw12345",
                                        "full_name": "Dr. Review Me", "role": "provider"})
revdoc_id = r.json()["id"]
check(verify_email("revdoc@example.com").status_code == 200, "doctor to review verifies email")
revdoc_headers = {"Authorization": "Bearer " + client.post(
    "/auth/login", data={"username": "revdoc@example.com", "password": "pw12345"}).json()["access_token"]}
r = client.post("/doctor-verification", headers=revdoc_headers, data={**form, "registration_number": "KMC 99999"},
                files={"certificate": ("cert.pdf", cert, "application/pdf")})
check(r.status_code == 200 and r.json()["status"] == "pending", "doctor submits details for review")

os.environ["MEDIPASS_REVIEWER_EMAILS"] = "PRIYA@example.com, drkumar@example.com"  # case/space-insensitive
check(client.get("/reviewer/me", headers=patient_headers).json() == {"is_reviewer": True}, "listed email is a reviewer")
data = client.get("/reviewer/doctors", headers=patient_headers).json()
row = next((d for d in data["doctors"] if d["id"] == revdoc_id), None)
check(row and row["status"] == "pending" and row["registration_number"] == "KMC 99999" and row["has_certificate"]
      and data["counts"]["pending"] >= 1, "pending list shows the doctor's details and certificate")
check(all(d["status"] == "pending" for d in data["doctors"]), "the pending tab only lists pending doctors")
check(client.get("/reviewer/doctors?status=bogus", headers=patient_headers).status_code == 400, "unknown tab rejected")
r = client.get(f"/reviewer/doctors/{revdoc_id}/certificate", headers=patient_headers)
check(r.status_code == 200 and r.content == cert, "reviewer opens the uploaded certificate")
check(client.get(f"/reviewer/doctors/{revdoc_id}/certificate", headers=revdoc_headers).status_code == 403,
      "a doctor can't open certificates through the reviewer API")

r = client.post(f"/reviewer/doctors/{revdoc_id}/decision", headers=patient_headers, json={"decision": "reject", "note": "no"})
check(r.status_code == 400, "rejecting needs a real reason")
r = client.post(f"/reviewer/doctors/{revdoc_id}/decision", headers=patient_headers,
                json={"decision": "reject", "note": "Registration number not found"})
check(r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["review_note"] == "Registration number not found",
      "reviewer rejects with a reason")
r = client.post(f"/reviewer/doctors/{revdoc_id}/decision", headers=patient_headers,
                json={"decision": "approve", "note": "Re-checked on NMC register"})
check(r.status_code == 200 and r.json()["status"] == "verified" and "Priya Sharma" in r.json()["reviewer"],
      f"reviewer approves; their name is recorded ({r.json().get('reviewer')})")
me = client.get("/doctor-verification/me", headers=revdoc_headers).json()
check(me["status"] == "verified", "the doctor now shows as verified")
vdoc = client.get("/doctor-verification/document", headers=revdoc_headers).json()
check("Priya Sharma" in (vdoc["verification"]["reviewer"] or ""), "the verification document names the reviewer")
db = SessionLocal()
try:
    notes = [n.message for n in db.query(models.Notification).filter(models.Notification.patient_id == revdoc_id)]
    audits = [a.action for a in db.query(models.AuditLog).filter(models.AuditLog.patient_id == revdoc_id)]
finally:
    db.close()
check(any("not approved" in n for n in notes) and any("has been verified" in n for n in notes),
      "the doctor is notified of each decision")
check(audits.count("doctor_verification_rejected") == 1 and audits.count("doctor_verification_approved") == 1,
      "each decision is audited")
kumar_id = client.get("/auth/me", headers=provider_headers).json()["id"]
r = client.post(f"/reviewer/doctors/{kumar_id}/decision", headers=provider_headers, json={"decision": "approve"})
check(r.status_code == 403, "a reviewer can't decide on their own verification")
os.environ.pop("MEDIPASS_REVIEWER_EMAILS", None)

# ---------------------------------------------------------------- 13k. review doctors by email (no reviewer account)
import re as _re  # noqa: E402

os.environ["MEDIPASS_REVIEWER_EMAILS"] = "boss@example.com, maildoc@example.com"
outbox = []


def _capture(to, subject, html, text="", attachments=None):
    outbox.append({"to": to, "subject": subject, "html": html, "text": text, "attachments": attachments or []})
    return True


r = client.post("/auth/register", json={"email": "maildoc@example.com", "password": "pw12345",
                                        "full_name": "Dr. Mail Review", "role": "provider"})
maildoc_id = r.json()["id"]
verify_email("maildoc@example.com")
maildoc_headers = {"Authorization": "Bearer " + client.post(
    "/auth/login", data={"username": "maildoc@example.com", "password": "pw12345"}).json()["access_token"]}
with mock.patch.object(email_utils, "send_email", side_effect=_capture):
    r = client.post("/doctor-verification", headers=maildoc_headers, data={**form, "registration_number": "KMC 55555"},
                    files={"certificate": ("cert.pdf", cert, "application/pdf")})
check(r.status_code == 200 and r.json()["status"] == "pending", "doctor submits (email flow)")
check([m["to"] for m in outbox] == ["boss@example.com"],
      f"every reviewer is emailed, but never the doctor themselves ({[m['to'] for m in outbox]})")
mail = outbox[0]
check("Dr. Mail Review" in mail["subject"] and "KMC 55555" in mail["subject"], "subject names the doctor and registration")
check(mail["attachments"] and mail["attachments"][0][0] == "cert.pdf" and mail["attachments"][0][1] == cert,
      "the certificate is attached")
check("KMC 55555" in mail["text"] and "Automatic checks" in mail["text"], "the email lists the details")
m = _re.search(r"/review-decision\?token=([^&\s]+)&action=approve", mail["text"])
check(m and "&action=reject" in mail["text"] and "&action=approve" in mail["html"], "Approve and Reject links in the email")
token = m.group(1)

d = client.get(f"/reviewer/email/{token}").json()
check(d["doctor"]["registration_number"] == "KMC 55555" and d["reviewer_email"] == "boss@example.com"
      and not d["stale"] and not d["decided"], "the link opens the request without logging in")
check(client.get(f"/reviewer/email/{token}/certificate").content == cert, "the certificate opens from the link")
check(client.get("/reviewer/email/not-a-real-token").status_code == 400, "a made-up link is rejected")
check(client.get(f"/reviewer/email/{token[:-3]}abc").status_code == 400, "a tampered link is rejected")
check(client.post(f"/reviewer/email/{token}/decision", json={"decision": "reject", "note": "x"}).status_code == 400,
      "rejecting by email needs a reason")
check(client.get("/doctor-verification/me", headers=maildoc_headers).json()["status"] == "pending",
      "opening the link changes nothing by itself")

# the doctor changes a detail -> new email; the old link can't be used any more
outbox.clear()
with mock.patch.object(email_utils, "send_email", side_effect=_capture):
    client.post("/doctor-verification", headers=maildoc_headers, data={**form, "registration_number": "KMC 55556"})
check(len(outbox) == 1, "changed details send a new email")
r = client.post(f"/reviewer/email/{token}/decision", json={"decision": "approve"})
check(r.status_code == 409 and "changed their details" in r.json()["detail"], "the old link stops working after a change")
check(client.get(f"/reviewer/email/{token}").json()["stale"] is True, "the old link shows it's out of date")
token = _re.search(r"token=([^&\s]+)&action=approve", outbox[0]["text"]).group(1)

r = client.post(f"/reviewer/email/{token}/decision", json={"decision": "approve", "note": "Checked NMC register"})
check(r.status_code == 200 and r.json()["status"] == "verified" and r.json()["reviewer"] == "boss@example.com",
      "approving from the email link verifies the doctor, recorded under the reviewer's email")
check(client.get("/doctor-verification/me", headers=maildoc_headers).json()["status"] == "verified", "doctor is verified")
r = client.post(f"/reviewer/email/{token}/decision", json={"decision": "reject", "note": "changed my mind"})
check(r.status_code == 409 and "Already decided" in r.json()["detail"], "a link can only be used once")
db = SessionLocal()
try:
    audits = [a.action for a in db.query(models.AuditLog).filter(models.AuditLog.patient_id == maildoc_id)]
finally:
    db.close()
check("doctor_verification_approved_via_email" in audits, "email decisions are audited")

os.environ["MEDIPASS_REVIEWER_EMAILS"] = "someone-else@example.com"
check(client.get(f"/reviewer/email/{token}").status_code == 403, "links stop working if the address is removed as reviewer")
os.environ.pop("MEDIPASS_REVIEWER_EMAILS", None)
with mock.patch.object(email_utils, "send_email", side_effect=_capture):
    outbox.clear()
    client.post("/doctor-verification", headers=maildoc_headers, data={**form, "registration_number": "KMC 55557"})
check(outbox == [], "no reviewers configured -> no emails")

# ---------------------------------------------------------------- 14. revoke
# ---------------------------------------------------------------- imaging (demo patient)
def unverified_for(doc_id):
    return [x for x in client.get("/records/unverified", headers=demo_headers).json()
            if x["source_document_id"] == doc_id]


# Gemini path: body part from the image
fake_gemini.next_payload = FAKE_CHEST_XRAY
r = upload("chest.png", make_blank_png(), "image/png", "lab_report", demo_headers)
check(r.status_code == 201, "X-ray image upload (Gemini path)")
[rec] = unverified_for(r.json()["id"])
check(rec["title"] == "X-ray of Chest" and rec["details"]["body_part"] == "chest",
      f"Gemini body part stored and titled ({rec['title']})")
check(rec["details"]["body_part_source"] == "ai" and rec["confidence"] == 0.95, "AI suggestion keeps its confidence")
check(rec["details"].get("is_fallback_date") is True, "image with no written date is flagged 'date not on document'")

# Gemini down, textless image uploaded as lab report -> imaging record, body part unknown
with mock.patch.object(documents_router, "extract_medical_records", side_effect=RuntimeError("503 UNAVAILABLE")):
    r = upload("xray_photo.png", make_blank_png(), "image/png", "lab_report", demo_headers)
check(r.status_code == 201, f"X-ray photo still uploads when Gemini is down (got {r.status_code}: {r.text[:120]})")
[unknown_rec] = unverified_for(r.json()["id"])
check(unknown_rec["details"]["body_part"] == "unknown" and unknown_rec["confidence"] == 0.0,
      "no body part guessed without AI -- patient must choose")

# Confirmation gate
r = client.post(f"/records/{unknown_rec['id']}/verify", json={}, headers=demo_headers)
check(r.status_code == 400, "can't verify an X-ray while its body part is unknown")
r = client.post(f"/records/{unknown_rec['id']}/verify",
                json={"corrected_details": {**unknown_rec["details"], "body_part": "shoulder"}}, headers=demo_headers)
check(r.status_code == 200 and r.json()["title"] == "X-ray of Shoulder", "patient picks the body part")
check(r.json()["details"]["body_part_source"] == "patient_confirmed"
      and r.json()["details"]["body_part_suggested"] == "unknown", "stored as patient-confirmed with the original suggestion kept")
r = client.post(f"/records/{rec['id']}/verify", json={"corrected_record_date": "2099-01-01"}, headers=demo_headers)
check(r.status_code == 400, "a future consultation date is rejected")
r = client.post(f"/records/{rec['id']}/verify", json={"corrected_record_date": "2025-08-21"}, headers=demo_headers)
check(r.status_code == 200 and r.json()["details"]["body_part_source"] == "patient_confirmed",
      "confirming the AI suggestion also marks it patient-confirmed")
check(r.json()["record_date"] == "2025-08-21" and "is_fallback_date" not in r.json()["details"],
      "patient-entered consultation date saved and the 'not on document' flag cleared")
r = client.get("/records/body-parts", headers=demo_headers)
codes = {bp["code"] for bp in r.json()}
check({"chest", "shoulder", "skull_head", "spine_cervical", "spine_thoracic", "spine_lumbar", "abdomen_pelvis",
       "arm", "forearm", "hand", "wrist", "thigh", "knee", "leg", "ankle", "foot"} <= codes and "unknown" not in codes,
      "body-part list covers every required region")

# DICOM: tag + AI agree
dcm = make_dicom("CHEST")
fake_gemini.next_payload = FAKE_CHEST_XRAY
r = upload("study.dcm", dcm, "application/octet-stream", "prescription", demo_headers)
check(r.status_code == 201 and r.json()["document_type"] == "lab_report", "DICOM accepted (octet-stream) and filed as lab report")
dicom_doc = r.json()["id"]
[drec] = unverified_for(dicom_doc)
check(drec["details"]["body_part_source"] == "dicom_metadata+ai" and drec["confidence"] >= 0.97,
      "DICOM tag and AI agree -> high confidence")
check(drec["record_date"] == "2026-08-01", "record dated from DICOM StudyDate")
r = client.get(f"/documents/{dicom_doc}/file", headers=demo_headers)
check(r.status_code == 200 and r.headers["content-type"] == "image/png", "View source renders DICOM as PNG")

# DICOM: tag and AI disagree
fake_gemini.next_payload = {**FAKE_CHEST_XRAY, "records": [{**FAKE_CHEST_XRAY["records"][0],
                            "details": {**FAKE_CHEST_XRAY["records"][0]["details"], "body_part": "shoulder"}}]}
r = upload("mislabelled.dcm", make_dicom("CHEST"), "application/dicom", "lab_report", demo_headers)
[crec] = unverified_for(r.json()["id"])
check(crec["details"]["body_part_source"] == "conflict" and crec["confidence"] <= 0.5
      and "DICOM tag says Chest" in crec["details"]["body_part_note"], "DICOM/AI disagreement flagged for the patient")

# DICOM with Gemini down: metadata only
with mock.patch.object(documents_router, "extract_medical_records", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")):
    r = upload("knee.dcm", make_dicom("KNEE", "DX"), "application/dicom", "lab_report", demo_headers)
[krec] = unverified_for(r.json()["id"])
check(krec["title"] == "X-ray of Knee" and krec["details"]["body_part_source"] == "dicom_metadata",
      "DICOM metadata identifies the body part when Gemini is down")

# Legacy discharge-summary documents still display after the type was removed
db = SessionLocal()
try:
    demo_id = db.query(models.User).filter(models.User.email == "patient@medipass.demo").first().id
    legacy = models.Document(patient_id=demo_id, uploaded_by=demo_id, file_name="old_discharge.pdf",
                             document_type="discharge_summary", content_type="application/pdf", raw_text="legacy")
    db.add(legacy)
    db.flush()
    db.add(models.MedicalRecord(
        patient_id=demo_id, record_type=models.RecordType.hospitalization, title="Admission at Sunrise Hospital",
        details=json.dumps({"text": "Pneumonia"}), record_date=__import__("datetime").date(2025, 11, 6),
        source_type=models.SourceType.ai_extracted, source_document_id=legacy.id, confidence=1.0,
        verification_status=models.VerificationStatus.patient_verified))
    db.commit()
    legacy_id = legacy.id
finally:
    db.close()
r = client.get(f"/documents/{legacy_id}", headers=demo_headers)
check(r.status_code == 200 and r.json()["document_type"] == "discharge_summary", "legacy discharge_summary document still readable")
r = client.get(f"/timeline/{demo_id}", headers=demo_headers)
check(any(x["title"] == "Admission at Sunrise Hospital" for x in r.json()["records"]),
      "legacy discharge_summary records still on the timeline")

# ---------------------------------------------------------------- AI summary citation repair
from app.routers.timeline import _clean_citations  # noqa: E402
_ids = {"a" * 32, "b" * 32}
_fixed = _clean_citations(
    f"x [medication](#{'a' * 32}], y [medication]\n(#{'b' * 32}). z [lab_result](#{'c' * 32}).", _ids)
check("](#" + "a" * 32 + ")" in _fixed and "](#" + "b" * 32 + ")" in _fixed and "c" * 32 not in _fixed
      and "[source]" in _fixed and "\n" not in _fixed,
      f"summary citations repaired; unknown ids dropped ({_fixed})")

# ---------------------------------------------------------------- Gemini 503 -> retry -> fallback model
calls = []


class Flaky:
    """Primary model always 503s; the fallback model answers."""

    def __init__(self):
        self.models = self

    def generate_content(self, model, contents, config=None):
        calls.append(model)
        if model == llm.GEMINI_MODEL:
            raise RuntimeError("503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}")
        return mock.Mock(text=f"Summary from {model}")


if llm.GEMINI_FALLBACK_MODELS:
    with mock.patch.object(llm, "get_gemini_client", return_value=Flaky()), mock.patch("time.sleep"):
        r = client.get(f"/timeline/{demo_id}/summary", headers=demo_headers)
    check(r.json()["summary"] == f"Summary from {llm.GEMINI_FALLBACK_MODELS[0]}",
          "503 on the primary model -> retried, then answered by the fallback model")
    check(calls.count(llm.GEMINI_MODEL) == 3, f"primary retried before switching (calls: {calls})")
else:
    print("SKIP: no MEDIPASS_GEMINI_FALLBACK_MODELS configured")

# ---------------------------------------------------------------- 14. revoke
r = client.post(f"/access-requests/{grant_id}/revoke", headers=patient_headers)
check(r.status_code == 200 and r.json()["status"] == "revoked", "patient revokes access")
check(client.get(f"/timeline/{patient_id}", headers=provider_headers).status_code == 403,
      "provider blocked again after revocation")
check(client.get("/consultations/mine", headers=provider_headers).json() == [],
      "revoked patient disappears from provider's recent records")
data = client.get("/provider/patients", headers=provider_headers).json()
check(patient_id not in [p["patient_id"] for p in data["active"]]
      and any(p["patient_id"] == patient_id and p["reason"] == "revoked" for p in data["inactive"]),
      "revoked patient moves to Inactive patients")

# ---------------------------------------------------------------- 15. audit log
r = client.get("/audit-log", headers=patient_headers)
check(r.status_code == 200, "patient fetches audit log")
actions = [entry["action"] for entry in r.json()]
for action in ["access_requested", "access_approved", "record_added", "access_revoked", "qr_code_created", "access_granted_via_qr"]:
    check(action in actions, f"audit log has {action}")
check(actions.count("access_granted_via_qr") == 1 and actions.count("qr_scanned_existing_patient") == 1,
      "each QR scan is audited once (one new patient, one already-a-patient)")

print("\nALL CHECKS PASSED")
