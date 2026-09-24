# Doctor verification

A doctor has to be verified before they can **add new patients**, whether by
**Request access** or by scanning a patient's QR code. Access they already
have keeps working. Patients see a **✓ Verified doctor** or **Not verified**
badge next to every doctor.

Code: `backend/app/routers/doctor_verification.py`,
`backend/review_doctors.py`, `frontend/src/pages/provider/ProviderProfilePage.jsx`,
`frontend/src/pages/provider/VerificationDocument.jsx`.

## What the doctor submits (My Profile)

| Field | Check |
|---|---|
| Specialization | Required |
| Hospital / clinic affiliation | Required. Also used to match prescriptions to the doctor's consultation notes |
| Medical registration number | Required, 3–25 letters/digits (e.g. `KMC 12345`) |
| Medical council | Required (NMC or a state council; suggestions offered) |
| Qualifications | Required (e.g. `MBBS, MD (Psychiatry)`) |
| Year of registration | Optional, 1950–this year |
| Practising since | Optional, 1950–this year. Used for years of experience; defaults to the registration year |
| Education history | Optional, up to 10 rows. Each row needs a degree and an institution; the year is optional (1950–this year). Empty rows are ignored |
| Other affiliations | Optional, one per line, up to 10. The primary hospital isn't repeated here |
| Registration or degree certificate | Required. PDF, JPEG, PNG or WEBP, 10 MB max |

Status goes **Not submitted → Under review → Verified** (or **Not
approved**, with the reviewer's reason). Changing any detail after
verification sends it back for review.

**Years of experience** = this year − (practising-since year, or the
registration year if that isn't given). Only the year is known, so this is
a count of calendar years.

## How it's verified

MediPass can't query the National Medical Commission or state council
registers automatically, because there's no public API. So:
1. **Automated:** completeness and format checks, and a certificate must be
   attached.
2. **Human reviewer:** checks the name and registration number on the
   [Indian Medical Register](https://www.nmc.org.in/information-desk/indian-medical-register/)
   (or the state council's site), and opens the uploaded certificate. This is
   done on the **Review doctors** screen (below), or from the command line in
   `backend/` with the backend venv:

   ```bash
   ./venv/Scripts/python.exe review_doctors.py list
   ./venv/Scripts/python.exe review_doctors.py show    doctor@example.com
   ./venv/Scripts/python.exe review_doctors.py approve doctor@example.com "Checked NMC register" --by "Dr. A. Reviewer"
   ./venv/Scripts/python.exe review_doctors.py reject  doctor@example.com "Registration number not found"
   ```

   `show` prints everything submitted, including education, other
   affiliations and the certificate's path. `--by` records who made the
   decision (default "MediPass reviewer"); it appears as **Reviewed by** on
   the verification document. The doctor gets a notification with the
   outcome.

The seeded `doctor@medipass.demo` account is pre-verified for demos. It has
no certificate on file, so its document shows that check as not met.

## Review doctors screen

Accounts whose email is listed in **`MEDIPASS_REVIEWER_EMAILS`**
(comma-separated, on the server) get a **Review doctors** item in the
sidebar. It works for a patient or a doctor account, and the badge shows how
many doctors are waiting.

- **Tabs:** *Waiting for review* (oldest first) · *Verified* · *Not approved* ·
  *Not submitted*, each with a count.
- **Each doctor card shows:**
  - name and email (and whether the email is verified);
  - specialization, hospital, registration number, council, year,
    qualifications, experience, education, other affiliations, submitted time;
  - **📄 Open certificate** and **🔎 Check the NMC register**;
  - the automatic checks (*6 of 7 met*, expandable);
  - the last decision (who, when, note).
- **✓ Approve** (optional note, asks to confirm) and **✗ Reject** (a reason of
  at least 5 characters is required, and the doctor sees it). A verified
  doctor can have their verification revoked the same way.
- **Safeguards:**
  - the decision records the reviewer as *"Name (email)"*, which appears on
    the doctor's verification document;
  - the doctor is notified, and it's audited (`doctor_verification_approved` /
    `_rejected`);
  - a reviewer can't decide on their own account.

API (reviewers only, otherwise 403): `GET /reviewer/me`,
`GET /reviewer/doctors?status=pending|verified|rejected|not_submitted|all`,
`GET /reviewer/doctors/{id}/certificate`,
`POST /reviewer/doctors/{id}/decision` `{"decision": "approve"|"reject", "note": "..."}`.

## Verification document

Once details are submitted, **My Profile → 📄 View verification document**
shows a structured document. **Print / Save as PDF** prints only the document
(print CSS hides the rest of the app).

| Section | Contents |
|---|---|
| Header | Doctor's name and email, document number `MPV-XXXXXXXX`, time generated, overall compliance |
| 1. Credentials and licence | Licence status (Verified / Under review / Not approved / Not submitted), registration number, council, year, qualifications, certificate file |
| 2. Education | Degree, institution, year |
| 3. Specialization, affiliations and experience | Specialization, primary hospital, other affiliations, years of experience and what they're counted from |
| 4. Verification record | Submitted at, reviewed at, reviewed by, reviewer's note, approval authority |
| 5. Medical board compliance | Each requirement with Met / Not met and details |

**Compliance checks** (required unless marked):

| Requirement | Met when |
|---|---|
| Registered with a recognised medical council | The council names the NMC, a state medical council, a dental council, or the homoeopathy/Indian-medicine councils |
| Registration number in a valid format | 3–25 letters/digits |
| Recognised medical qualification | Qualifications or education include MBBS or an equivalent (BDS, BAMS, BHMS, BUMS, MD, MS, DNB, DM, MCh, MRCP, FRCS) |
| Registration or degree certificate on file | A certificate was uploaded |
| Specialization and hospital affiliation declared | Both filled in |
| Registration checked against the official register by a reviewer | Status is Verified and the review happened after the latest submission |
| Education history provided *(recommended)* | At least one row |

**Overall:** *Not submitted* (no details) → *Not compliant* (rejected, or a
required detail missing or invalid) → *Pending review* (details complete,
waiting for the reviewer) → *Compliant* (everything required is met).

The document says plainly that the NMC register was checked by a person,
not automatically.

## Setting

`MEDIPASS_REQUIRE_VERIFIED_DOCTORS` defaults to `true`. With `false`,
unverified doctors can add patients, but patients still see the badge.

## Database

The three new fields (`education`, `affiliations`, `practice_start_year` on
`doctor_credentials`) are nullable. Existing databases get them
automatically at startup (`database.add_missing_columns`); existing rows
are left as they are.

## API

| Method | Path | Who |
|---|---|---|
| GET | `/doctor-verification/me` | Doctor: their details, status and years of experience |
| POST | `/doctor-verification` | Doctor: submit or update (multipart form; `education` and `affiliations` are JSON lists; `certificate` file) |
| GET | `/doctor-verification/certificate` | Doctor: their uploaded certificate |
| GET | `/doctor-verification/document` | Doctor: the verification document as structured JSON |
