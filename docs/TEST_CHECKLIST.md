# MediPass: full test checklist

For the live site (https://medipass-frontend-production.up.railway.app) or a
local run. Tick each box when the **Expected** result happens.

**You'll need:**
- two browsers, or one normal and one private window (patient + doctor logged in at once);
- two email addresses you can open (one patient, one doctor);
- a phone (for the QR scan and the mobile layout);
- test files:
  - a clear prescription photo;
  - a handwritten prescription;
  - a lab-report PDF;
  - an X-ray image;
  - optionally a DICOM `.dcm` file.

Server shell for admin steps: `railway ssh --service MediPass-AI` (from the
project folder).

---

## 0. Deployment health
- [ ] `https://medipass-ai-production.up.railway.app/health` shows `{"status":"ok"}`
- [ ] The frontend link opens the login page; `/login` and `/verify-email` don't 404
- [ ] Railway shows both services **Online**; the backend has the volume `medipass-ai-volume`
- [ ] **Persistence:** create an account, redeploy the backend (Deployments → ⋮ → Redeploy), log in again → the account is still there

## 1. Accounts and email
- [ ] **Register as patient** → "Check your email!" screen with your address
- [ ] The email arrives (check Spam/Promotions) from **"MediPass"**, with a *Verify email* button
- [ ] **Verify email** link → "verified" page → you can log in
- [ ] **Resend email** on the check-email screen → a new email; a second click within a minute says *wait … seconds*
- [ ] **Log in before verifying** → "Email not verified" and a **Resend verification email** link
- [ ] **Register again with the same, still unverified, unused email** → allowed; restarts sign-up and sends a new link
- [ ] **Register with an already verified email** → "Email already registered. Log in, or use Forgot password."
- [ ] **Forgot password** → reset email → set a new password → log in with it
- [ ] **Wrong password** → "Incorrect email or password."
- [ ] Server shell: `cat /data/logs/email.log` shows `SENT` for each email above
- [ ] **Sign out** is visible at the bottom of the sidebar on long pages and on a phone

## 2. Doctor verification
- [ ] **Register as Doctor**, verify email, log in → sidebar says **Doctor**, dashboard shows *"⚠ Verify your doctor profile"*
- [ ] **Unverified doctor tries Scan patient QR / Request access** → blocked: *"Your doctor profile isn't verified yet…"*
- [ ] **My Profile validation:**
  - [ ] a registration number of `!` → rejected
  - [ ] no certificate → rejected
  - [ ] an education row with a degree but no institution → rejected
- [ ] **Submit a valid form** (with education rows, other affiliations, practising-since) → status **Under review**
- [ ] **View verification document** → shows *Pending review*
- [ ] Server shell: `python review_doctors.py list` → your email is `pending`
- [ ] `python review_doctors.py show <email>` → all details and the certificate path
- [ ] `python review_doctors.py approve <email> "note" --by "Name"` → Profile shows **✓ Verified doctor**, and there's a notification
- [ ] **Verification document** → **Compliant**, with:
  - [ ] 5 sections;
  - [ ] years of experience;
  - [ ] *Reviewed by* your name;
  - [ ] every compliance check ✓
- [ ] **Print / Save as PDF** → only the document prints
- [ ] **Change a profile detail and resubmit** → back to *Under review*
- [ ] (Optional) `reject <email> "reason"` → *Not approved* with the reason; the doctor can fix it and resubmit
- [ ] **Review doctors screen:** with `MEDIPASS_REVIEWER_EMAILS` set to your account:
  - [ ] a **Review doctors** item appears, with a badge for the number waiting;
  - [ ] other accounts don't see it
- [ ] **On a waiting doctor's card:**
  - [ ] all their details show;
  - [ ] **Open certificate** opens the file;
  - [ ] **Check the NMC register** opens the NMC site
- [ ] **✗ Reject** without a reason → *"Write the reason…"*; with a reason → moves to *Not approved*
- [ ] **✓ Approve** → moves to *Verified*, with *"Last decision … by <you>"*; the doctor sees **✓ Verified doctor** and their document names you
- [ ] **Your own doctor account** on the list → *"another reviewer has to decide"*
- [ ] **Review by email:** when a doctor submits their details, each reviewer address gets *"MediPass: verify Dr. …"* (check Spam), with:
  - [ ] the details;
  - [ ] the certificate attached;
  - [ ] Approve / Reject buttons
- [ ] **Approve** in the email → a confirmation page opens without logging in → **Confirm** → *"✓ Doctor approved"*; the doctor is verified
- [ ] **The same link again** → *"Already decided …"*; **Reject** needs a reason; after the doctor changes their details, the old email's link says *"use the newer email"*

## 3. Doctor gets access to a patient
- [ ] **Patient → My QR code**:
  - [ ] choose what to share and for how long → a QR code appears with a countdown;
  - [ ] the doctor clicks **Scan patient QR** and scans it → *"✓ added to your patients"*
- [ ] **Scanning the same patient again** → "already your patient" and their profile opens
- [ ] **Request access** (doctor → Find a patient by email):
  - [ ] the patient sees it in **Access requests**;
  - [ ] the patient approves with limited sharing (e.g. medications only) → the doctor sees only those record types
- [ ] **Patient's Access requests:**
  - [ ] shows *✓ Verified doctor* and the hospital;
  - [ ] **Revoke** → the doctor loses access at once and the patient moves to *Inactive patients*

## 4. Upload and AI extraction (patient)
- [ ] **Clear prescription photo** → *Uploaded… Detected as prescription*
- [ ] **Verify records** lists each medicine, with:
  - [ ] medicine, dose, timing;
  - [ ] **Course** (e.g. *10 days · 31 May – 9 Jun · completed …*);
  - [ ] a confidence badge (hover shows *"AI reading 95% · 4 of 4 checks passed"*)
- [ ] The **consultation date** matches the date written on the paper (day/month order, e.g. 12/10/22 → 12 Oct 2022)
- [ ] **No date on the paper** → *"Date not on document"* and you're asked to enter it
- [ ] **Prescription box** at the top of each upload:
  - [ ] "Prescribed by / Hospital" is filled in (or open to fill if missing);
  - [ ] save a name → it shows "Prescribed by Dr. …"
- [ ] **Missing field** (e.g. no timing) → lower confidence; under 70% shows *"Low confidence… Missing or unclear: …"*
- [ ] **Confirm as-is / Edit before confirming** (change dose or duration) / **Remove** each work
- [ ] **Lab-report PDF** → lab results with values
- [ ] **X-ray image:**
  - [ ] the title is *"X-ray of Chest"* (etc.);
  - [ ] a one-line description (*"Chest radiograph (X-ray) showing the lungs…"*), with no long garbage text;
  - [ ] you must pick or confirm the **body part** before confirming
- [ ] (Optional) **DICOM `.dcm`** → the body part is taken from the file, and the date is the study date
- [ ] **Upload the identical file again** → *"You already uploaded this exact file… on …"* with **View source** / **Upload anyway**
- [ ] **Upload anyway**, or a different photo of the same prescription → repeated entries show *"⚠ Looks like a duplicate of …"* with **Remove duplicate**
- [ ] **View source** on any record opens the original file

## 5. Timeline and record pages (patient)
- [ ] **Your timeline** shows only verified records, each with:
  - [ ] the consultation date;
  - [ ] *Logged in MediPass <date>*
- [ ] **Sort by:**
  - [ ] consultation date newest/oldest → correct order;
  - [ ] **Logged in MediPass newest/oldest** → correct order;
  - [ ] record type → grouped;
  - [ ] after a reload the choice is remembered
- [ ] **Show** filter (Medications / Diagnoses / Lab results…) with counts
- [ ] **Medicines card → View all medicines:**
  - [ ] dose and timing chips;
  - [ ] a course line (*day X of Y · N days left* / *completed N days ago* / *As needed*)
- [ ] **Diagnosis card → View all diagnoses:**
  - [ ] long text wraps inside the box;
  - [ ] nothing sticks out and there's no sideways scrolling
- [ ] **Prescription card:** *"Prescribed by … · Edit"* (🔒 once a link to it is confirmed)
- [ ] **AI summary panel** loads, citations jump to records (if Gemini is unavailable, a basic summary shows)
- [ ] **Conflict flags** appear for real conflicts; there are no "No record available between…" messages
- [ ] **Medications** and **Lab results** pages: same cards, with **Sort by** (including logged date)
- [ ] **Patient dashboard:** the counters are right, including *Active medications* (courses not yet ended); tiles open their pages

## 6. Doctor's work with a patient
- [ ] **Dashboard:**
  - [ ] *Welcome, Dr. …* and the stats;
  - [ ] the **Active patients** section;
  - [ ] *Recent consultations*
- [ ] **Active patients page** (sidebar):
  - [ ] count and *Last updated*; **↻ Refresh**;
  - [ ] status filters with counts; search; all 5 sort options
- [ ] **Patient card metrics:** under your care (days), last visit, follow-up, access days left, records shared
- [ ] **Statuses:**
  - [ ] new patient without a note → **New**;
  - [ ] a note with *"Follow up on <today's date>"* → **Follow-up required**;
  - [ ] a note with *"urgent referral"* → **Critical**;
  - [ ] **Mark: …** menu → *Set by you*;
  - [ ] **Status: automatic** → back to the automatic status
- [ ] **View patient → Back** returns to the page you came from
- [ ] **Add a consultation note** (typed) → it appears on the patient's timeline, and the patient gets a notification
- [ ] **Voice dictation (🎤):**
  - [ ] speak a note → the text is structured into fields;
  - [ ] the mic check explains problems (no mic or permission);
  - [ ] if AI structuring fails, the transcript is kept
- [ ] **The consultation date defaults to today's local date** (check just after midnight if possible)

## 7. Consultation ↔ prescription linking
Set up: the doctor's account name = the doctor's name on the patient's prescription (e.g. *Abhijna Chattopadhyay*); the patient has shared **medications**.
- [ ] **The doctor adds a consultation note** dated on the prescription's date that mentions its medicines → **🔗 Related documents** shows:
  - [ ] `L-XXXXXX`;
  - [ ] the prescription with its medicines, doses and courses;
  - [ ] *why* it matched;
  - [ ] *⏳ Awaiting the patient's confirmation*
- [ ] **Patient → Verify records → Confirm document links (1)** shows:
  - [ ] the doctor's consultation (*🩺 Consultation by Dr. …*);
  - [ ] the prescription
- [ ] **✓ Yes** (confirm the "final" prompt):
  - [ ] both sides show *✓ Confirmed by the patient … final*;
  - [ ] the doctor has no **Change link** option
- [ ] **The prescription card** shows **🔗 Linked consultation** with the doctor's full note (title, text, specialty, hospital)
- [ ] **Show on timeline** / **Go to note** scroll to and highlight the other card, even with a type filter on
- [ ] **Reject** a proposed link → *unmatched*; it's not proposed again
- [ ] **Prescription with no doctor name:**
  - [ ] the note stays unmatched;
  - [ ] the patient adds *Prescribed by* → it links automatically
- [ ] **A note by a different doctor** → *"No prescription from Dr. X … yet"* and **Link manually**
- [ ] **A confirmed link is locked:**
  - [ ] editing the prescriber shows 🔒;
  - [ ] deleting the note is refused
- [ ] **Activity log** shows linked / confirmed / rejected / prescriber-edited entries

## 8. Notifications and activity log
- [ ] Notifications arrive for:
  - [ ] doctor-added records;
  - [ ] access by QR;
  - [ ] verification outcome (doctor)
- [ ] **The Activity log** lists:
  - [ ] access requested/approved/revoked;
  - [ ] QR created/scanned;
  - [ ] records added;
  - [ ] link events;
  - [ ] duplicate removals
- [ ] **The Verify records badge** = records waiting + links waiting

## 9. Layout and devices
- [ ] **Phone** (or a narrow browser window): no sideways scrolling on any page; dates stack above the content; Sign out is reachable
- [ ] **Tablet width:** cards and the Active patients grid lay out cleanly
- [ ] Browser console (F12) → no red errors while using the pages

## 10. Security and privacy
- [ ] A doctor **without** access to a patient can't open their timeline (e.g. after revoke)
- [ ] A doctor with **limited sharing** doesn't see unshared record types, prescriptions or other doctors' notes
- [ ] A patient can't see another patient's data
- [ ] The demo accounts (`patient@medipass.demo`) **don't** exist on the live site
- [ ] GitHub repo: no `.env`, databases, uploads or logs

## 11. Backup AI path (optional)
- [ ] When Gemini is unavailable (quota, outage), an upload still works using local text reading (Tesseract), and the records are marked with lower confidence
- [ ] The timeline AI summary falls back to a basic summary instead of an error

## 12. Admin tools (server shell)
- [ ] `python review_doctors.py list | show | approve | reject` work
- [ ] `python find_duplicates.py --email <patient>` lists duplicates and changes nothing
- [ ] Only after reviewing the list: `--apply` backs up the database first, then removes the duplicates
- [ ] `cat /data/logs/email.log` shows every email attempt

## 13. Automated tests (local)
- [ ] In `backend/`: `./venv/Scripts/python.exe test_smoke.py` → **ALL CHECKS PASSED** (268 checks, no real emails sent, no real AI calls)
- [ ] In `frontend/`: `npm run build` succeeds; `npm run lint` shows no errors
