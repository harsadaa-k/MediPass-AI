# Active Patients (doctor dashboard)

Its own page in the doctor's sidebar (**Active patients**, under *Scan
patient QR*), and also a clearly bordered section on the dashboard below the
general statistics. It lists every patient the doctor currently has access
to. **View patient** opens the patient, and *Back* returns to the page it
was opened from.

Code: `backend/app/routers/provider_patients.py`,
`frontend/src/pages/provider/ActivePatients.jsx`,
`frontend/src/pages/provider/ActivePatientsPage.jsx`.

## What it shows

- **Header:** the number of active patients and **Last updated** (time of
  the last fetch). The list refreshes itself every minute, and there's a
  **↻ Refresh** button.
- **Status filters:** All / Critical / Follow-up required / New / Ongoing,
  each with its count.
- **Search** by name or email, and **Sort by**: status (most urgent first),
  name, longest since last visit, longest under your care, access ending
  soonest.
- **One card per patient**, with a coloured left edge for its status:
  - name, email and what they share;
  - status pill and the reason for it;
  - **Under your care** (days since access was granted);
  - **Last visit** (the doctor's latest note, e.g. "5 days ago");
  - **Follow-up** ("Due in 3 days", "Due today", "Overdue by 2 days", or
    "None set");
  - **Access** (days until the grant ends; highlighted at 3 days or less);
  - **Records** shared, and notes written by this doctor;
  - **View patient**, and a status menu to set the status by hand.
- **Inactive patients** (collapsed, underneath): patients whose access
  expired or was revoked, kept apart from the active list.

## Status rules

The first rule that applies wins:

| Status | When |
|---|---|
| Set by the doctor | The doctor picked a status in the card's menu ("Set by you"). **Status: automatic** returns to the rules below |
| **Critical** | A record the doctor can see, dated in the last 90 days, mentions an urgent or critical finding (e.g. *urgent*, *critical*, *emergency*, *suicidal*, *high risk*, *ICU*, *inpatient care*, *sepsis*, *stroke*, *myocardial infarction*, *anaphylaxis*). The reason shows the date and the words found |
| **Follow-up required** | The doctor's latest note sets a follow-up date that has arrived: *"review after 2 weeks"* (counted from the note's date) or *"follow up on 15/06/2025"* (day/month/year) |
| **New** | Access granted in the last 7 days and no note from this doctor yet |
| **Ongoing** | Everything else |

Only records inside the patient's sharing scope are read (the same rule as
the timeline), plus the doctor's own notes. The automatic statuses are
prompts for the doctor, not clinical triage.

## Day counts

Counted in whole calendar days using the server's local date (records carry
calendar dates, and timestamps are converted from UTC before counting), so
a visit yesterday always shows as "yesterday" whatever the time of day. See
[`DAYS_AND_CONFIDENCE.md`](DAYS_AND_CONFIDENCE.md).

## API

| Method | Path | Who |
|---|---|---|
| GET | `/provider/patients` | Doctor: `{generated_at, total_active, counts, active: [...], inactive: [...]}` |
| PUT | `/provider/patients/{patient_id}/status` | Doctor with access: `{"status": "critical" \| "follow_up" \| "new" \| "ongoing" \| null, "note": "..."}` (`null` = automatic) |

Doctor-set statuses are stored in the `patient_status_flags` table (one row
per doctor and patient).
