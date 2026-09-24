"""
Review doctor verification requests (there is no admin screen yet).

Run from backend/ with the backend venv:
    ./venv/Scripts/python.exe review_doctors.py list
    ./venv/Scripts/python.exe review_doctors.py show   doctor@example.com
    ./venv/Scripts/python.exe review_doctors.py approve doctor@example.com "Checked NMC register" --by "Dr. A. Reviewer"
    ./venv/Scripts/python.exe review_doctors.py reject  doctor@example.com "Registration number not found"

--by records who approved it; it's shown as the approval authority on the
doctor's verification document (default "MediPass reviewer").

Before approving, check the registration number and name against the
official register (https://www.nmc.org.in/information-desk/indian-medical-register/
or the state medical council's site) and open the uploaded certificate
(its path is printed by `show`).
"""
import json
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from app import models  # noqa: E402
from app.database import Base, SessionLocal, engine, add_missing_columns  # noqa: E402

Base.metadata.create_all(bind=engine)
add_missing_columns(["doctor_credentials"])


def main(argv):
    reviewer = "MediPass reviewer"
    if "--by" in argv:
        i = argv.index("--by")
        if i + 1 >= len(argv) or not argv[i + 1].strip():
            print("--by needs the reviewer's name.")
            return 1
        reviewer = argv[i + 1].strip()
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 2 or argv[1] not in {"list", "show", "approve", "reject"}:
        print(__doc__)
        return 1
    cmd = argv[1]
    db = SessionLocal()
    try:
        if cmd == "list":
            rows = (db.query(models.DoctorCredential, models.User)
                    .join(models.User, models.User.id == models.DoctorCredential.provider_id)
                    .order_by(models.DoctorCredential.submitted_at.desc()).all())
            unsubmitted = [u for u in db.query(models.User).filter(models.User.role == models.UserRole.provider)
                           if not any(u.id == c.provider_id for c, _ in rows)]
            for cred, user in rows:
                print(f"{cred.status:9} {user.email:32} {user.full_name:24} reg {cred.registration_number} ({cred.medical_council})")
            for u in unsubmitted:
                print(f"{'none':9} {u.email:32} {u.full_name:24} (hasn't submitted details)")
            return 0

        if len(argv) < 3:
            print("Give the doctor's email.")
            return 1
        user = db.query(models.User).filter(models.User.email == argv[2]).first()
        cred = user and db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == user.id).first()
        if not cred:
            print("No verification request from that email.")
            return 1
        profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == user.id).first()

        if cmd == "show":
            print(f"Name:            {user.full_name} <{user.email}>")
            print(f"Specialization:  {profile.specialty if profile else '-'}")
            print(f"Hospital:        {profile.hospital_name if profile else '-'}")
            print(f"Registration:    {cred.registration_number} - {cred.medical_council} ({cred.registration_year or 'year ?'})")
            print(f"Qualification:   {cred.qualification}")
            for e in json.loads(cred.education or "[]"):
                print(f"Education:       {e['degree']}, {e['institution']}{', ' + str(e['year']) if e.get('year') else ''}")
            for a in json.loads(cred.affiliations or "[]"):
                print(f"Also at:         {a}")
            if cred.practice_start_year:
                print(f"Practising since {cred.practice_start_year}")
            print(f"Certificate:     {cred.certificate_path}")
            print(f"Status:          {cred.status}  {cred.review_note or ''}"
                  f"{'  (by ' + cred.reviewer + ')' if cred.reviewer else ''}")
            return 0

        note = argv[3] if len(argv) > 3 else ""
        if cmd == "reject" and not note:
            print("Give a reason the doctor will see, e.g. \"Registration number not found on NMC register\".")
            return 1
        cred.status = "verified" if cmd == "approve" else "rejected"
        cred.reviewed_at = datetime.utcnow()
        cred.reviewer = reviewer
        cred.review_note = note or None
        db.add(models.Notification(
            patient_id=user.id,  # notifications are per user; the doctor sees it in their account
            message=("Your doctor profile has been verified." if cmd == "approve"
                     else f"Your doctor verification was rejected: {note}"),
        ))
        db.commit()
        print(f"{user.email}: {cred.status}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
