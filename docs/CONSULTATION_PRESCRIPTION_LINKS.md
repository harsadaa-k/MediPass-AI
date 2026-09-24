# Linking consultation notes to prescriptions

When a doctor adds a consultation note, MediPass automatically proposes a
link to the prescription **the same doctor** wrote that the patient
uploaded. The hospital/clinic on the prescription is used as supporting
evidence. **The patient must accept the link**; once accepted it is final and
can't be changed or removed by anyone. The link is visible from both sides.

Code: `backend/app/linking.py` (matching), `backend/app/routers/links.py`
(API), `frontend/src/components/RelatedLinks.jsx` (UI).

## Data structure: `record_links`

There is one row per consultation note. It holds the **current** link state;
every change is also written to `audit_logs`.

| Column | Meaning |
|---|---|
| `id` | Primary key. Shown to users as the reference **`L-XXXXXX`** (first 6 characters). |
| `patient_id` | The patient. |
| `consultation_id` | The doctor's consultation note (`medical_records`, `doctor_generated`, type `consultation`). **Unique.** |
| `document_id` | The linked prescription (`documents`, type `prescription`, uploaded by the patient). `NULL` unless linked. |
| `status` | `linked` (proposed, awaiting the patient), `confirmed` (accepted by the patient — final), `ambiguous` (several equally good matches) or `unmatched` (none, or rejected). |
| `method` | `auto` or `manual`. The auto-linker never changes `manual` rows. |
| `score` | Match score 0–1 for automatic links. |
| `match_reason` | Human-readable explanation, e.g. *"prescribed by Dr. R. Mehta (matches Dr. R. Mehta), 3 days apart, mentions the same medicines"*. |
| `candidate_document_ids` | JSON list of the top candidates when `ambiguous`. |
| `process` | Which system step produced it, e.g. `auto-linker v1 (consultation added)` / `(prescription uploaded)` / `(backfill)` / `manual override`. |
| `created_by` | The user who made a manual override (`NULL` for automatic links). |
| `override_reason` | Required reason for a manual override. |
| `created_at`, `updated_at` | Timestamps (UTC). |

Audit trail: each change writes one of these actions to `audit_logs`, with
`target_type = "record_link"` and `target_id` set to the link's id:
- `record_linked` — an automatic link was proposed;
- `record_link_needs_review` — the note matches more than one prescription;
- `record_link_overridden` — someone changed a proposal by hand;
- `record_link_confirmed` — the patient accepted the link (final);
- `record_link_rejected` — the patient rejected the proposal.

The actor is the doctor whose note triggered it, or the user who overrode it.
The patient's **Activity log** shows these as, for example, *"A consultation
note by Dr. R. Mehta was linked to a prescription"*.

The prescribing doctor and hospital are captured at upload time:
- **Gemini path:** document-level `prescribing_doctor` and `hospital_name` are
  copied into each record's `details.doctor_name` / `details.hospital_name`.
- **Local-OCR path:** the first "Dr. …" in the text
  (`extraction.find_doctor_name`) and the first letterhead line naming a
  hospital/clinic (`extraction.find_hospital_name`).

**The patient can fill in or correct the doctor and hospital.** Many
prescriptions (handwritten slips, online consults) have no letterhead the AI
can read, and without a doctor's name a prescription can never be linked. So:
- **Verify records** shows a *Prescribed by / Hospital / clinic* box above the
  entries of each uploaded prescription. It opens by itself when no doctor
  was found.
- On **Your timeline**, each prescription's Medicines card shows *"Prescribed
  by …"* with **Edit** (or **Add doctor**).
- Saving writes `doctor_name` / `hospital_name` (and `prescriber_source:
  "patient"`) on every entry from that upload, adds "Dr." if missing, audits
  `prescriber_edited`, and re-runs matching. That covers unsettled notes plus
  proposals that pointed at this prescription.
- Locked (🔒, API 409) once a confirmed link uses the prescription.
- `PATCH /documents/{id}/prescriber` `{"doctor_name": "...", "hospital_name": "..."}` (patient only, prescriptions only).

## Matching algorithm

**Triggers:**
1. A doctor adds a consultation note → that note.
2. The patient uploads a prescription → re-run every automatic link for
   that patient that is still `unmatched` or `ambiguous`. This handles
   *"prescription uploaded after the note"*.
3. Listing links for a patient → back-fill notes written before the feature
   existed.

**Steps:**
1. **Candidates:** the patient's own uploaded prescriptions.
2. **Doctor match (required):** the similarity between the note author's
   name and the prescription's doctor must be **≥ 0.75**. The comparison
   ignores titles such as "Dr."/"MBBS", accepts initials ("R. Mehta" ~
   "Rajesh Mehta"), and tolerates small spelling differences.
3. **Score each eligible prescription:**
   ```
   score = 0.45 × name_similarity
         + 0.25 × date_score          date_score = 1 / (1 + days_apart / 14)
                                      (×0.9 if the prescription is dated after the note)
         + 0.15 × context_score       share of the prescription's medicines / diagnoses
                                      mentioned in the note (doubled, capped at 1)
         + 0.15 × hospital_score      prescription's hospital vs the doctor's profile
                                      hospital ("City Clinic" ~ "CITY CLINIC, Bengaluru");
                                      0 if either is unknown
   ```
4. **Decide:**
   - No eligible prescription → `unmatched`: *"No prescription from Dr. X
     among the patient's uploads yet — it will link automatically when one
     is uploaded."*
   - One, or the best beats the runner-up by **≥ 0.10** → `linked`
     (a proposal, until the patient accepts it).
   - Otherwise → `ambiguous`; the top 3 are kept for a person to choose.

**Edge cases:**

| Case | Result |
|---|---|
| No prescription from that doctor | `unmatched` with the reason; relinks automatically on the next prescription upload |
| Prescription uploaded after the note | Linked on upload (process `prescription uploaded`) |
| Several prescriptions from the same doctor | Nearest date wins; if dates tie, medicine names mentioned in the note decide; if still tied, `ambiguous` |
| Prescription by a different doctor | Never auto-linked; can still be linked manually |
| Note deleted | Its link row is deleted too |
| Wrong automatic link | The patient rejects it, or a manual override (below) |
| Link accepted by the patient | Final: no override, no rejection, the note can't be deleted, the auto-linker leaves it alone |

## Patient confirmation

Every proposed link (automatic or manual) waits for the patient:
- **Verify records → "Confirm document links"** lists each proposal with the
  note, the prescription (doctor, hospital, date, medicines), why it
  matched and **View source**.
- **✓ Yes, this is the right prescription** → `confirmed`, after a "this is
  final" prompt. From then on it can't be changed or removed by the
  patient, the doctor or the system (API returns 409).
- **No, wrong prescription** (optional reason) → `unmatched`. The
  auto-linker won't propose it again; the doctor can propose another one
  manually, which again needs the patient's acceptance.
- The **Verify records** sidebar badge counts records *and* links waiting
  for the patient.

```
POST /links/{link_id}/accept          (patient only)
POST /links/{link_id}/reject          { "reason": "..." }   (patient only)
```

## Manual override

**Who can do it:**
- **the patient**;
- **the doctor who wrote the note**, while they have access that includes
  prescriptions.

A reason of at least 5 characters is required and is stored and shown.

The override can:
- link any of the patient's uploaded prescriptions, even one from another
  doctor;
- or mark the note as having *no related prescription*.

Manual links are never changed by the auto-linker. Overrides are only
possible **before** the patient confirms.

```
POST /links/consultation/{consultation_id}/override
{ "document_id": "<prescription id>" | null, "reason": "..." }
```

## What users see

**On a consultation note → 🔗 Related documents `L-XXXXXX`**
- *Linked (proposed):*
  - the prescription (doctor (hospital) · date · medicines);
  - how it was linked (automatically, with the reason, or manually by whom,
    with their reason);
  - **Show on timeline**, which scrolls to and highlights the prescription;
  - **View source**, which opens the uploaded file;
  - *⏳ Awaiting the patient's confirmation*; the patient also gets **✓ Yes**
    / **No, wrong prescription** buttons here;
  - **Change link** (note's author or patient).
- *Confirmed:* the same details plus *"✓ Confirmed by the patient on <date> —
  this link is final"*, and no change option.
- *Ambiguous:* ⚠ the reason plus the possible prescriptions, and **Choose
  prescription**.
- *Unmatched:* the reason and **Link manually**.
- The editor lists every uploaded prescription with its score and reason.
  Ones from other doctors are dimmed. There is also a *No related
  prescription* option, a reason box, and **Save link**, which stays disabled
  until a reason is entered.

**On the prescription → 🔗 Linked consultation(s)**
- For each note, the doctor's consultation as written from their account:
  *"🩺 Consultation by Dr. X (specialty, hospital) · date"*, the note's title,
  its text and any follow-up. Also the same `L-` reference, and whether it was
  linked automatically or manually and whether the patient confirmed it.
- The note's content is shown to the patient, the note's author, and doctors
  with full-history access, the same people who see consultation notes on the
  timeline. Other doctors see *"The note's content isn't shared with you."*
- The consultation is also shown in **Verify records → Confirm document
  links**, so the patient sees what the doctor wrote before accepting.

**On the consultation note**, the Related documents panel also lists what the
prescription says: each medicine with dose, timing and course, and any
diagnosis. **Show on timeline** turns off a type filter that would hide the
prescription before scrolling to it.
- **Go to note** scrolls to and highlights it.

Both the patient's **Your timeline** and the doctor's patient view show the
same panels. A doctor whose access doesn't include medications sees only
*"A linked prescription exists but the patient hasn't shared prescriptions
with you."*

## API

| Method | Path | Who |
|---|---|---|
| GET | `/links/patient/{patient_id}` | The patient, or a doctor with access |
| GET | `/links/consultation/{id}/candidates` | Same, if prescriptions are shared |
| POST | `/links/consultation/{id}/override` | The patient, or the note's author |
