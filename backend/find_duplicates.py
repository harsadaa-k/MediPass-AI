"""
List (and optionally remove) duplicate records caused by uploading the same
prescription more than once.

Run from backend/ with the backend venv:
    ./venv/Scripts/python.exe find_duplicates.py                      # all patients, list only
    ./venv/Scripts/python.exe find_duplicates.py --email a@b.com      # one patient, list only
    ./venv/Scripts/python.exe find_duplicates.py --email a@b.com --apply

Listing changes nothing. --apply first copies the SQLite database to
medipass.db.bak-<time>-before-dedupe, then deletes the extra copies.

Which copy is kept in each group:
  1. the one from a prescription a consultation note is linked to, else
  2. the most recently logged one (newest extraction).
Doctor-written records are never removed. Matching rules: app/duplicates.py.
"""
import os
import shutil
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from app import duplicates, models  # noqa: E402
from app.database import DATABASE_URL, Base, SessionLocal, add_missing_columns, engine  # noqa: E402

Base.metadata.create_all(bind=engine)
add_missing_columns(["doctor_credentials", "documents"])


def clusters(records):
    """Group records that duplicate each other (union-find)."""
    parent = {r.id: r.id for r in records}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(records):
        for b in records[i + 1:]:
            if duplicates.is_duplicate(a, b):
                parent[find(a.id)] = find(b.id)
    groups = {}
    for r in records:
        groups.setdefault(find(r.id), []).append(r)
    return [g for g in groups.values() if len(g) > 1]


def main(argv):
    apply = "--apply" in argv
    email = argv[argv.index("--email") + 1] if "--email" in argv and argv.index("--email") + 1 < len(argv) else None
    db = SessionLocal()
    try:
        patients = db.query(models.User).filter(models.User.role == models.UserRole.patient)
        if email:
            patients = patients.filter(models.User.email == email)
        patients = patients.all()
        if not patients:
            print("No such patient.")
            return 1

        linked_docs = {l.document_id for l in db.query(models.RecordLink)
                       .filter(models.RecordLink.status.in_(["linked", "confirmed"])) if l.document_id}
        to_delete = []
        for patient in patients:
            docs = db.query(models.Document).filter(models.Document.patient_id == patient.id).all()
            by_hash = {}
            for d in docs:
                h = duplicates.document_hash(db, d)
                has_records = db.query(models.MedicalRecord.id).filter(
                    models.MedicalRecord.source_document_id == d.id).first()
                if h and has_records:
                    by_hash.setdefault(h, []).append(d)
            same_files = [g for g in by_hash.values() if len(g) > 1]

            records = [r for r in duplicates.timeline_records(db, patient.id)
                       if r.source_type != models.SourceType.doctor_generated]
            groups = clusters(records)
            if not same_files and not groups:
                continue

            print(f"\n=== {patient.full_name} <{patient.email}>")
            for g in same_files:
                print(f"  Same file uploaded {len(g)} times: {g[0].file_name} "
                      f"({', '.join(f'{d.upload_date:%d %b %H:%M}' for d in sorted(g, key=lambda d: d.upload_date))})")
            for g in groups:
                g.sort(key=lambda r: (r.source_document_id in linked_docs, r.created_at or datetime.min), reverse=True)
                keep, extra = g[0], g[1:]
                print(f"  {keep.record_type.value}: {keep.title} ({keep.record_date}) x{len(g)}")
                print(f"      keep   {keep.title!r} logged {keep.created_at:%d %b %H:%M}")
                for r in extra:
                    print(f"      remove {r.title!r} logged {r.created_at:%d %b %H:%M}")
                to_delete.extend(extra)
        db.commit()  # hashes computed for older uploads

        print(f"\n{len(to_delete)} duplicate record(s) found.")
        if not to_delete:
            return 0
        if not apply:
            print("Nothing changed. Re-run with --apply to remove them (the database is backed up first).")
            return 0

        if DATABASE_URL.startswith("sqlite:///"):
            path = DATABASE_URL.replace("sqlite:///", "", 1)
            backup = f"{path}.bak-{datetime.now():%Y-%m-%d-%H%M}-before-dedupe"
            shutil.copyfile(path, backup)
            print(f"Backup: {os.path.abspath(backup)}")
        else:
            print("Not SQLite: take a database backup first, then re-run with --apply --yes.")
            if "--yes" not in argv:
                return 1
        ids = [r.id for r in to_delete]
        db.query(models.Notification).filter(models.Notification.related_record_id.in_(ids)).update(
            {models.Notification.related_record_id: None}, synchronize_session=False)
        for r in to_delete:
            db.add(models.AuditLog(patient_id=r.patient_id, actor_id=r.patient_id, action="duplicate_record_removed",
                                   target_type="medical_record", target_id=r.id))
            db.delete(r)
        db.commit()
        print(f"Removed {len(ids)} duplicate record(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
