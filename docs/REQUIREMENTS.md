# MediPass — Software Requirements Document (Prototype / MVP)

**Version:** 1.0
**Prepared for:** Global Innovation Hackathon 2026 — Build for a Better Future (Bharat Academix)
**Team:** srijith11.2006 — Srijith S (Team Leader), Harsada K

---

## 1. Introduction

### 1.1 Purpose
This document defines the functional and non-functional requirements for the MediPass
prototype: an AI-assisted, patient-controlled medical history platform. It is the
reference used to build the working demo — every module built in code traces back to
a requirement listed here.

### 1.2 Product Summary
MediPass converts fragmented medical records (patient-uploaded legacy documents and
provider-generated records) into a single, structured, source-traceable, chronological
medical timeline. Patients control who can see their history and what parts of it;
authorized doctors can view permitted history and add new records, which flow back
into the same timeline.

### 1.3 Scope of This Build
This document covers the **prototype/MVP** scope only — enough to demonstrate the
core loop end-to-end (patient uploads → AI extracts → patient verifies → timeline
built → doctor requests access → patient consents → doctor views + adds a record →
timeline updates). Items explicitly out of scope for the MVP are listed in §7.

---

## 2. Stakeholders / User Roles

| Role | Description |
|---|---|
| **Patient** | Owns their medical history. Uploads old records, verifies AI-extracted data, grants/revokes provider access, views their own timeline. |
| **Provider (Doctor)** | Requests access to a patient's history, views only what was granted, adds new consultations/prescriptions/diagnoses, which are attributed to them. |
| **System (AI layer)** | Classifies documents, extracts structured data, scores confidence, flags conflicts and record gaps. Never makes clinical decisions. |

Hospitals and labs are modelled in the data layer for future extension but are **not**
separate MVP user roles (see §7).

---

## 3. Functional Requirements

### FR-1 Authentication & Accounts
- FR-1.1 A user can register as either a **patient** or a **provider**, with email + password.
- FR-1.2 A user can log in and receive a session token (JWT).
- FR-1.3 Every API action is scoped to the logged-in user's role; a patient cannot call provider-only actions and vice versa.

### FR-2 Document Upload & AI Extraction
- FR-2.1 A patient can upload a medical document (prescription, lab report, discharge summary) with a declared or auto-detected document type.
- FR-2.2 The system runs an extraction pipeline that produces one or more structured **medical records** (medication, lab result, diagnosis, etc.) from the document.
- FR-2.3 Each extracted record carries a **confidence score**. Records below a threshold are marked `unverified` and must be confirmed by the patient before being treated as reliable.
- FR-2.4 The original uploaded document is always retained and linked to every record extracted from it (source traceability).

### FR-3 Patient Verification
- FR-3.1 A patient can view all `unverified` records extracted from their uploads.
- FR-3.2 A patient can confirm a record as-is, or edit its fields and then confirm it. Either action sets its status to `patient_verified`.

### FR-4 Medical Timeline
- FR-4.1 The system presents all of a patient's records (patient-provided, AI-extracted + verified, and provider-generated) in chronological order.
- FR-4.2 Every record displayed shows its **source** (who created it / where it came from) and links back to the original document where applicable.
- FR-4.3 The system detects and flags **conflicts** — e.g. two records of the same type (such as an allergy) with contradictory values — without deciding which is correct.
- FR-4.4 The system detects **gaps** — periods with no records — and labels them as "no record available," never as "no treatment occurred."

### FR-5 Provider Access & Consent
- FR-5.1 A provider can request access to a specific patient's history.
- FR-5.2 A patient can approve or deny a request, and select which categories of information are shared (e.g. medications, labs, allergies, or full history).
- FR-5.3 A provider can only view the categories and time range they were granted.
- FR-5.4 A patient can revoke a previously granted access at any time.

### FR-6 Provider Record Creation
- FR-6.1 A provider with an approved, active access grant can add a new consultation, prescription, diagnosis, or hospitalization record for that patient.
- FR-6.2 Every provider-created record is attributed to that provider (`source_type = doctor-generated`) and immediately appears on the patient's timeline.

### FR-7 Audit Log
- FR-7.1 Every access grant, access request, and provider-added record is logged with actor, action, and timestamp.
- FR-7.2 A patient can view their own access/audit history.

---

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Security** — passwords hashed (bcrypt); all authenticated endpoints require a valid JWT; role-based authorization enforced server-side, not just in the UI. |
| NFR-2 | **Data provenance** — every medical record row stores its source type, creator, and (if applicable) source document — non-negotiable, since this is MediPass's core differentiator. |
| NFR-3 | **Traceability** — no record's structured data may exist without either a source document reference (AI-extracted) or a creator reference (provider-generated). |
| NFR-4 | **Usability** — the patient verification step must be a single confirm/edit action, not a multi-page form, so the demo flow stays fast. |
| NFR-5 | **Portability** — the backend must run locally with a file-based database (SQLite) for the prototype, with a documented path to swap in PostgreSQL. |
| NFR-6 | **No silent overwrites** — conflicting information is never auto-resolved; both versions are retained and flagged. |
| NFR-7 | **Honesty about AI** — the system never presents an unverified, low-confidence extraction as fact in the timeline without a visible flag. |

---

## 5. System Architecture (Prototype)

```
   React (Vite) frontend
          │  REST (JSON) over HTTPS/HTTP
          ▼
   FastAPI backend  ──── JWT auth (passlib + python-jose)
          │
          ├── AI extraction (Gemini multimodal LLM,
          │   fallback: Tesseract OCR + rule-based)
          ├── Timeline & Intelligence module
          │     (conflict detection, gap detection)
          └── SQLAlchemy ORM
                   │
                   ▼
              SQLite (dev) → PostgreSQL (production path)
```

### 5.1 Data Model (core entities)

- **User** — id, email, hashed_password, role (`patient`/`provider`), full_name
- **PatientProfile** — user_id, date_of_birth, blood_group, emergency_contact
- **ProviderProfile** — user_id, specialty, hospital_name
- **Document** — id, patient_id, uploaded_by, file_name, document_type, upload_date
- **MedicalRecord** — id, patient_id, record_type, title, details (JSON), record_date,
  source_type, source_document_id, created_by, confidence, verification_status
- **AccessGrant** — id, patient_id, provider_id, status, scope (JSON), requested_at,
  responded_at, expires_at
- **AuditLog** — id, patient_id, actor_id, action, target_type, target_id, timestamp

---

## 6. Technology Stack (Prototype)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3 + FastAPI | Fast to build, auto-generated OpenAPI docs, async-ready, matches the AI/document-processing components being Python too. |
| Auth | passlib (bcrypt) + python-jose (JWT) | Standard, well-tested, minimal setup. |
| ORM / DB | SQLAlchemy + SQLite (dev) | Zero-config for a prototype; swappable for PostgreSQL via one connection-string change. |
| Frontend | React (Vite) | Fast dev loop, works as a responsive web app per the original proposal's fallback option. |
| AI extraction | Google Gemini (multimodal LLM) with fallback models | Reads photos and PDFs, including handwriting and X-rays, into structured records with confidence scores. |
| Fallback extraction | Tesseract OCR + PyMuPDF + rule-based extractor | Keeps uploads working when the AI service is unavailable. |
| Imaging | pydicom | Reads DICOM X-rays and their body-part / study-date tags. |
| Deployment | Railway (backend + frontend), Brevo email | HTTPS hosting with a persistent volume; transactional email over HTTPS. |

---

## 7. Out of Scope for the MVP (Future Work)

Built beyond the original MVP scope: real OCR + LLM extraction (Gemini with a
local OCR fallback), QR-code / short-code access, voice dictation for doctors,
doctor verification with reviewer approval, consultation-prescription linking,
AI sharing recommendations and the AI clinical summary.

Still future work:
- Hospital and lab accounts as distinct roles
- ABDM/ABHA interoperability
- Multilingual extraction and voice input, caregiver/family accounts
- Production-grade encryption at rest, full audit compliance tooling

---

## 8. Build Plan (Phased) — status

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Backend scaffold: models, auth, DB | ✅ Done |
| 2 | Document upload + AI extraction + patient verification | ✅ Done |
| 3 | Timeline with conflict detection | ✅ Done |
| 4 | Provider access requests, consent, record creation | ✅ Done |
| 5 | Audit log | ✅ Done |
| 6 | React frontend | ✅ Done |
| 7 | End-to-end smoke test + demo script | ✅ Done |
| 8 | QR sharing, doctor verification, linking, notifications, deployment | ✅ Done |
