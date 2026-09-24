# Adding a patient by QR code

The patient shows a QR code from MediPass; the doctor scans it; the patient
is on the doctor's list immediately. This replaces the old **Emergency QR**
(anonymous read-only links) and, for in-person visits, the
request → approve round-trip.

The request/approve flow (**Find a patient → Request access**) still exists
for doctors who aren't with the patient.

## For patients

1. Open **My QR code**.
2. Choose what the doctor may see (*medications, labs, allergies,
   diagnoses* or *full history*), how long they keep access (7 / 30 / 90
   days) and how long the code can be scanned (15 min / 1 h / 24 h).
3. Tap **Generate my QR code** and show it to the doctor.
4. When they scan it, your screen changes to *"✓ Dr. … scanned your code and
   has been added"*. You also get a notification and an entry in your
   **Activity log**.
5. To stop sharing later: **Access requests → Revoke** next to the doctor.

Good to know:
- A code works **once**. Generating a new code cancels any unused one, and
  **Cancel this code** does too.
- Showing the code is how you give consent, so only show it to a doctor you
  want to share with. If you showed it by mistake, cancel it.

## For doctors

1. **Dashboard → 📷 Scan Patient QR** (or **Scan patient QR** in the sidebar).
2. **Start camera** and point it at the patient's code. If the camera isn't
   available, use **Upload a photo of the code**, or paste the code/link the
   patient reads out under *"Doctor's camera not working?"*.
3. You're taken back to the dashboard with a green
   *"✓ <patient> added to your patients"* banner, and the patient is
   highlighted under **Active patients**. Use **Open patient** to start.

If the patient is **already your active patient**, nothing about your access
changes: their profile opens straight away with *"<patient> is already your
patient"* and your current sharing and end date. The patient's screen and
notifications say the same. (If your access had expired or been revoked,
scanning restores it with the patient's new choices.) Codes that are used,
cancelled or expired are rejected with a message asking for a new one.

A phone's own camera app also works: the code is a link
(`…/add-patient/<code>`). Opening it while logged in as a doctor adds the
patient. If you aren't logged in, you're asked to log in first and the
patient is added straight after.

## How it's secured

| Measure | Detail |
|---|---|
| Unguessable code | 256-bit random token (`secrets.token_urlsafe(32)`). |
| Not stored in the clear | Only its SHA-256 hash is in the database, so a copied database can't be used to replay codes. |
| Single use, short-lived | Default 15 minutes, maximum 24 hours; marked used on first scan. |
| One live code per patient | A new code cancels older unused ones. |
| Doctors only | Only provider accounts can redeem codes, and only patients can create them. |
| Minimum necessary | The doctor gets exactly the scope and duration the patient picked; the timeline, AI summary and records APIs enforce the scope. |
| Transparent | `qr_code_created`, `access_granted_via_qr` / `qr_scanned_existing_patient` go in the patient's activity log (with the doctor's name), plus a notification naming the doctor and what they can see. |
| Revocable | Standard revoke in **Access requests**; access also lapses automatically at the chosen end date. |

API: `POST /patient-qr` (patient), `GET /patient-qr/{id}`,
`POST /patient-qr/{id}/revoke`, `POST /patient-qr/redeem` (doctor). See
`backend/app/routers/patient_qr.py`.

## Privacy and compliance notes

The design follows the consent principles in India's Digital Personal Data
Protection Act 2023 and ABDM's consent model, and HIPAA's minimum-necessary
idea:
- **Consent is specific:** the patient chooses what is shared and for how
  long.
- **Consent is informed:** the screen says what the code shares.
- **Consent is an affirmative act:** the patient generates and shows the code.
- **Consent can be withdrawn:** via Revoke.
- **Consent is recorded:** in the audit log.

Scanning skips a separate approval step. That is only acceptable because
the patient's in-person act of showing the code *is* the consent. Don't
reuse this flow for cases where the patient isn't present.

**This is a prototype, not a compliance certification.** Before real patient
data is involved you still need at least:
- HTTPS;
- a legal review of the consent wording;
- data-retention and breach policies;
- server-side rate limiting on `/patient-qr/redeem`;
- a production database with encryption at rest.

## What changed from Emergency QR

- **Removed:** the Emergency QR page, the anonymous
  `/emergency/<token>` read-only view and the `/emergency` API. Old emergency
  links stop working (they were short-lived anyway).
- **Why:** the new code is for adding the patient to a doctor's account, not
  for anonymous viewing.
- **If you need anonymous paramedic access again**, it would have to come
  back as a separate feature. It is not part of this flow.
