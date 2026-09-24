# MediPass Frontend (Prototype)

React (Vite) app implementing Phase 6: a patient dashboard and a provider
dashboard wired to the FastAPI backend.

## Setup

```bash
cd frontend
npm install
cp .env.example .env    # edit VITE_API_URL if your backend isn't on the default port
npm run dev
```

Open the URL Vite prints (default `http://127.0.0.1:5173`). Make sure the
backend is running first (see `../backend/README.md`) — the frontend talks
to it over plain REST.

## Demoing the full loop

The complete 28-step script (with expected results and sample documents) is
in [`../docs/DEMO_SCRIPT.md`](../docs/DEMO_SCRIPT.md). Short version:

1. Register a **patient** account, then a **provider** account (use the
   role picker on the sign-up screen).
2. As the patient: go to **Upload a document**. On a phone this opens your
   camera directly; on desktop it opens a file picker. Take a photo of (or
   choose an image/PDF of) a prescription, or use any photo with visible
   printed/written text as a stand-in for a demo. This runs through real
   Tesseract OCR — no pasted text involved.
3. Go to **Verify records** and confirm (or edit) each extracted entry.
   Low-confidence lines (genuinely low, based on how well OCR read the
   image) are flagged for extra care. Click "View source" to open the
   original photo/PDF you uploaded, right next to what was extracted from it.
4. Check **Your timeline** — the verified records now appear, source-coded
   by where they came from (the colored left edge on each row).
5. Log out, log in as the **provider**. Go to **Find a patient**, search by
   the patient's email, and request access.
6. Log back in as the patient, go to **Access requests**, pick which
   categories to share, and approve.
7. Log back in as the provider, open **My requests → View patient**. You
   can now see the shared timeline and add a new consultation/prescription
   — it appears on the patient's timeline immediately.
8. Try adding an allergy record that contradicts the uploaded one — the
   patient's timeline will show a conflict flag instead of silently
   picking one as correct.

## Project layout

```
src/
  api.js                REST client + token storage
  AuthContext.jsx        Auth state (current user, login/register/logout)
  App.jsx                  Routes between the auth screen and each dashboard
  index.css, styles/layout.css   Design tokens + layout
  components/
    Sidebar, Badge, Timeline, TimelineRecord, FlagBanner
  pages/
    AuthPage.jsx
    PatientDashboard.jsx   + pages/patient/*  (upload, verify, timeline, access, audit)
    ProviderDashboard.jsx  + pages/provider/* (find patient, my requests, patient view, add record)
```

## Notes

- Auth tokens are stored in `localStorage` for this prototype. A production
  build should move to httpOnly cookies to reduce XSS exposure.
- Upload runs a real OCR pipeline on the backend (see `../backend/README.md`
  "Installing Tesseract") — make sure that's installed or upload will show
  a clear error explaining what's missing.
