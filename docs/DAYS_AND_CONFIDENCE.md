# Day counts and confidence scores

## Treatment courses (number of days)

Prescriptions write durations in many ways. MediPass reads the duration
and turns it into a number of days and an end date. It is counted
**inclusively from the consultation date**: a 10-day course starting
31 May 2025 ends 9 June 2025.

Code: `backend/app/durations.py`, `frontend/src/dates.js`,
`frontend/src/components/CourseInfo.jsx`.

| Written | Read as |
|---|---|
| `x 10 days`, `for 5 days`, `x10d`, `10 din` | days |
| `1 week`, `x 2 wks` | weeks (7 days each) |
| `1 month`, `x 3 months` | calendar months |
| `1 year` | calendar years |
| `5/7`, `2/52`, `3/12` | medical shorthand: 5 days, 2 weeks, 3 months |
| `one`, `two` … `thirty` | number words |
| `SOS`, `as needed`, `PRN` | "As needed", with no end date |
| `continue`, `long-term`, `till next visit` | "Ongoing", with no end date |

**Where the duration comes from:**
- **New uploads:** Gemini now returns a separate `duration` field. If it
  leaves the duration inside the timing or notes ("1-0-1 for 5 days"), it
  is pulled out from there.
- **Existing records:** the duration is read from `duration`, `timing`,
  `notes` or the raw OCR line. Nothing is stored; the course is worked out
  each time a record is read. So it also follows any date or duration the
  patient corrects.

**Leap years and month lengths:** months and years are calendar-based. If
the start day doesn't exist in the target month, the count rolls to the
1st of the next month.
- 1 month from 31 Jan 2024 ends 29 Feb 2024 (30 days).
- 1 month from 31 Jan 2023 ends 28 Feb 2023 (29 days).
- 1 year from 29 Feb 2024 is 366 days.
- 5 days from 26 Feb 2024 ends 1 Mar 2024.

**Time zones:** all arithmetic is on plain calendar dates, never times.
- In the browser, `dates.js` never parses `"2025-05-31"` with
  `new Date()`, because that means UTC midnight and shifts a day west of
  UTC. It counts days between local calendar dates instead, which is also
  safe across DST changes.
- The default date for a new consultation and for a voice note is the
  **local** day. It used to be the UTC day, which gave yesterday's date
  before 05:30 in India.
- Timestamps (stored in UTC) are converted to local time before
  "Logged in MediPass" dates and day counts are shown.

**What's shown:**
- **Timeline → Medicines:** each medicine gets a line like *"10 days ·
  May 31, 2025 – Jun 9, 2025 · completed 472 days ago"*. While a course is
  running it says *"day 3 of 10 · 8 days left"*; before it starts, *"starts
  in 2 days"*.
- **Medications page:** the same line, as **Course**.
- **Verify records:** the medication card shows **Course**, and **Edit
  before confirming** has a **Duration** field.
- **Patient dashboard → Active medications:** a medicine counts while its
  course hasn't ended. A medicine with no written duration counts for 90
  days from its date, as before.
- **Doctor's Active Patients:** days under care, days since the last visit,
  follow-up due or overdue, and days of access left (see
  [`ACTIVE_PATIENTS.md`](ACTIVE_PATIENTS.md)).

The API adds `course` to every medication record: `{duration,
duration_days, start_date, end_date, ongoing}`. It is `null` when no
duration is written.

## Confidence score

Previously the badge showed the model's own rating, which Gemini sets at
about 0.95 for almost everything. Now the stored confidence combines that
rating with checks done in code:

```
confidence = base × (0.5 + 0.5 × checks_passed / checks_total)
```

- **base:** the model's self-rating, or Tesseract's legibility score on the
  local-OCR path. It is clamped to 0–1, and is 0.7 if missing.
- **checks**, per record type:

| Record type | Checks |
|---|---|
| Medication | medicine named · dose with a number and unit (mg, ml, IU, tablets…) · timing given · date written on the document |
| Diagnosis, allergy | clear title · date written on the document |
| Lab result, consultation, hospitalization | clear title · details text present · date written on the document |

**Examples:**

| Case | Confidence |
|---|---|
| A complete record rated 0.95 | Stays 95% |
| Rated 0.9, no timing (3 of 4 checks) | 0.9 × 0.875 = 79% |
| Diagnosis rated 0.9, no date on the document (1 of 2 checks) | 0.9 × 0.75 = 68%, shown as *Low confidence* |

**Rules that still apply:**
- A medication with no medicine name or dose is capped at 60%.
- Below 70% the verify card is flagged *Low confidence* and lists what's
  missing.
- **X-ray / scan images** keep their own score: how sure the AI is of the
  body part, or 0 if unknown, so the patient must choose it.

**Seeing the breakdown:** hover over any confidence badge, e.g. *"AI
reading 95% · 3 of 4 checks passed · missing: timing given"*. The inputs
are stored in `details.confidence_basis`.

Records already in the database keep the confidence they were saved with.
The new scoring applies to new uploads.

Code: `backend/app/confidence.py` (used by `llm.py` and `extraction.py`),
`frontend/src/components/ConfidenceBadge.jsx`.
