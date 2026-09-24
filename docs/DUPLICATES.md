# Duplicate uploads and records

Uploading the same prescription more than once used to put the same
medicines on the timeline several times. Now there are three safeguards.

Code: `backend/app/duplicates.py`, `backend/find_duplicates.py`,
`frontend/src/pages/patient/UploadDocument.jsx`, `VerifyQueue.jsx`.

## 1. Same file uploaded again (blocked before any AI call)

Every upload's SHA-256 is stored (`documents.content_sha256`; older uploads
get theirs computed the first time they're compared). If the patient already
uploaded the identical file and it still has entries, the upload stops with:

> ⚠ You already uploaded this exact file ("…png") on 23 Sep 2026. Its records
> are already in MediPass. **View source** · **Upload anyway**

API: `409` with `detail = {code: "duplicate_upload", message, document_id,
file_name, uploaded_at}`. Sending `allow_duplicate=true` uploads it anyway.
An earlier copy whose entries were all removed doesn't count.

## 2. Same prescription, different photo (flagged in Verify records)

A new entry is flagged *"Looks like a duplicate of X (date), already on your
timeline"* with **Remove duplicate** when it matches an entry already on the
timeline:
- same record type and consultation date, from a different upload, and
- **medications:** medicine names at least 85% similar after dropping
  "Tab./Cap./Syp." and brackets. This tolerates reading slips such as
  *Zocalm* vs *Zolcalm*. The doses must agree if both have one, so
  *Ecosprin 70mg* vs *40mg* is **not** a duplicate.
- **everything else:** near-identical title **and** text. Generic titles
  such as *"Note from prescription"* only match if the text matches too.

Nothing is removed automatically.

## 3. Cleaning up existing duplicates

```bash
./venv/Scripts/python.exe find_duplicates.py                           # list, all patients
./venv/Scripts/python.exe find_duplicates.py --email a@b.com           # list, one patient
./venv/Scripts/python.exe find_duplicates.py --email a@b.com --apply   # remove
```

- Listing changes nothing, except saving file fingerprints for older uploads.
- `--apply` first copies the database to
  `medipass.db.bak-<time>-before-dedupe`. It then removes the extra copies and
  audits each one as `duplicate_record_removed`.
- **Which copy is kept:** the one from a prescription a consultation note is
  linked to; otherwise the most recently logged one.
- Doctor-written records are never removed.
