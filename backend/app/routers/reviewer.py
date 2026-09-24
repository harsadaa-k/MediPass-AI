"""
Reviewing doctor verification requests, without the review_doctors.py
command line. Two ways:

* Review doctors screen: any logged-in account whose email is listed in
  MEDIPASS_REVIEWER_EMAILS (comma-separated) sees it in the sidebar.
* By email: when a doctor submits (or changes) their details, every
  reviewer address gets an email with the details, the certificate attached,
  and Approve / Reject links. Reviewers don't need a MediPass account.

Either way a reviewer can't decide on their own verification. Every decision
is stored on the credential (reviewer, time, note), audited, and the doctor
is notified -- the same as the CLI.
"""
import os
from datetime import datetime, timedelta
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth, email_utils
from ..database import get_db
from ..storage import read_upload
from .doctor_verification import _json_list, compliance_checks, overall_compliance, years_of_experience

router = APIRouter(prefix="/reviewer", tags=["reviewer"])

STATUSES = ("pending", "verified", "rejected", "not_submitted")
NMC_REGISTER = "https://www.nmc.org.in/information-desk/indian-medical-register/"


def reviewer_emails() -> set:
    return {e.strip().lower() for e in os.environ.get("MEDIPASS_REVIEWER_EMAILS", "").split(",") if e.strip()}


def is_reviewer(user: models.User) -> bool:
    return (user.email or "").lower() in reviewer_emails()


def require_reviewer(user: models.User = Depends(auth.get_current_user)) -> models.User:
    if not is_reviewer(user):
        raise HTTPException(status_code=403, detail="Only MediPass reviewers can do this.")
    return user


def _reviewer_label(user: models.User) -> str:
    return f"{user.full_name} ({user.email})"


def _doctor_out(db: Session, doctor: models.User) -> dict:
    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == doctor.id).first()
    cred = db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == doctor.id).first()
    checks = compliance_checks(cred, profile)
    return {
        "id": doctor.id,
        "name": doctor.full_name,
        "email": doctor.email,
        "email_verified": doctor.is_email_verified,
        "registered_at": doctor.created_at,
        "status": cred.status if cred else "not_submitted",
        "specialty": profile.specialty if profile else None,
        "hospital_name": profile.hospital_name if profile else None,
        "registration_number": cred.registration_number if cred else None,
        "medical_council": cred.medical_council if cred else None,
        "registration_year": cred.registration_year if cred else None,
        "qualification": cred.qualification if cred else None,
        "education": _json_list(cred.education) if cred else [],
        "affiliations": _json_list(cred.affiliations) if cred else [],
        "practice_start_year": cred.practice_start_year if cred else None,
        "years_of_experience": years_of_experience(cred),
        "has_certificate": bool(cred and cred.certificate_path),
        "certificate_file_name": cred.certificate_file_name if cred else None,
        "submitted_at": cred.submitted_at if cred else None,
        "reviewed_at": cred.reviewed_at if cred else None,
        "reviewer": cred.reviewer if cred else None,
        "review_note": cred.review_note if cred else None,
        "compliance": {"overall": overall_compliance(cred, checks), "checks": checks},
    }


def _certificate_response(cred: models.DoctorCredential) -> Response:
    if not cred or not cred.certificate_path:
        raise HTTPException(status_code=404, detail="No certificate uploaded.")
    try:
        content = read_upload(cred.certificate_path)
    except OSError:
        raise HTTPException(status_code=404, detail="The certificate file is missing on the server.")
    return Response(content=content, media_type=cred.certificate_content_type or "application/octet-stream")


def apply_decision(db: Session, doctor: models.User, cred: models.DoctorCredential, approve: bool,
                   note: str, reviewer_label: str, actor_id: str, via: str = "") -> None:
    """Record the decision, notify the doctor and audit it (screen and email links)."""
    cred.status = "verified" if approve else "rejected"
    cred.reviewed_at = datetime.utcnow()
    cred.reviewer = reviewer_label
    cred.review_note = note or None
    db.add(models.Notification(
        patient_id=doctor.id,  # notifications are per user; the doctor sees it in their account
        message=("Your doctor profile has been verified." if approve
                 else f"Your doctor verification was not approved: {note}"),
    ))
    db.add(models.AuditLog(
        patient_id=doctor.id, actor_id=actor_id,
        action=("doctor_verification_approved" if approve else "doctor_verification_rejected") + via,
        target_type="doctor_credential", target_id=cred.id,
    ))
    db.commit()


def _check_note(decision: str, note: Optional[str]) -> str:
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'.")
    note = (note or "").strip()[:500]
    if decision == "reject" and len(note) < 5:
        raise HTTPException(status_code=400, detail="Give the doctor a reason (at least 5 characters).")
    return note


class DecisionIn(BaseModel):
    decision: str            # "approve" | "reject"
    note: Optional[str] = None


# ---------------------------------------------------------------- Review doctors screen

@router.get("/me")
def reviewer_status(user: models.User = Depends(auth.get_current_user)):
    """Lets the app show the Review doctors page only to reviewers."""
    return {"is_reviewer": is_reviewer(user)}


@router.get("/doctors")
def list_doctors(
    status: str = "pending",
    db: Session = Depends(get_db),
    reviewer: models.User = Depends(require_reviewer),
):
    if status not in (*STATUSES, "all"):
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join((*STATUSES, 'all'))}.")
    doctors = db.query(models.User).filter(models.User.role == models.UserRole.provider).all()
    rows = [_doctor_out(db, d) for d in doctors]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    if status != "all":
        rows = [r for r in rows if r["status"] == status]
    # oldest request first, so nobody waits longest
    rows.sort(key=lambda r: (r["submitted_at"] or r["registered_at"] or datetime.min))
    return {"counts": counts, "doctors": rows, "you": reviewer.id}


@router.get("/doctors/{doctor_id}/certificate")
def doctor_certificate(
    doctor_id: str,
    db: Session = Depends(get_db),
    reviewer: models.User = Depends(require_reviewer),
):
    cred = db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == doctor_id).first()
    return _certificate_response(cred)


@router.post("/doctors/{doctor_id}/decision")
def decide(
    doctor_id: str,
    payload: DecisionIn,
    db: Session = Depends(get_db),
    reviewer: models.User = Depends(require_reviewer),
):
    note = _check_note(payload.decision, payload.note)
    if doctor_id == reviewer.id:
        raise HTTPException(status_code=403, detail="You can't review your own verification.")
    doctor = db.query(models.User).filter(models.User.id == doctor_id,
                                          models.User.role == models.UserRole.provider).first()
    cred = doctor and db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == doctor.id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="This doctor hasn't submitted verification details.")
    apply_decision(db, doctor, cred, payload.decision == "approve", note, _reviewer_label(reviewer), reviewer.id)
    return _doctor_out(db, doctor)


# ---------------------------------------------------------------- review by email
# The links carry a signed token tied to one exact submission, so they stop
# working once it's decided or the doctor changes anything. They open a
# confirmation page (frontend /review-decision); nothing changes until the
# reviewer presses the button there, so mail scanners that "click" links
# can't approve anyone.

EMAIL_LINK_DAYS = 14
_PURPOSE = "doctor_review"


def _submission_stamp(cred: models.DoctorCredential) -> str:
    return cred.submitted_at.isoformat() if cred.submitted_at else ""


def make_review_token(cred: models.DoctorCredential, reviewer_email: str) -> str:
    payload = {
        "purpose": _PURPOSE, "cred": cred.id, "sub": _submission_stamp(cred), "rev": reviewer_email,
        "exp": datetime.utcnow() + timedelta(days=EMAIL_LINK_DAYS),
    }
    return jwt.encode(payload, auth.SECRET_KEY, algorithm=auth.ALGORITHM)


def _read_token(db: Session, token: str):
    invalid = HTTPException(status_code=400, detail="This review link is invalid or has expired.")
    try:
        data = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    except JWTError:
        raise invalid
    if data.get("purpose") != _PURPOSE:
        raise invalid
    cred = db.query(models.DoctorCredential).filter(models.DoctorCredential.id == data.get("cred")).first()
    doctor = cred and db.query(models.User).filter(models.User.id == cred.provider_id).first()
    if not cred or not doctor:
        raise HTTPException(status_code=404, detail="This verification request no longer exists.")
    reviewer_email = (data.get("rev") or "").lower()
    if reviewer_email not in reviewer_emails():
        raise HTTPException(status_code=403, detail="This email address is no longer a MediPass reviewer.")
    stale = data.get("sub") != _submission_stamp(cred)
    return cred, doctor, reviewer_email, stale


@router.get("/email/{token}")
def email_review_details(token: str, db: Session = Depends(get_db)):
    """Opened from the email link: what the reviewer is deciding on."""
    cred, doctor, reviewer_email, stale = _read_token(db, token)
    return {"doctor": _doctor_out(db, doctor), "reviewer_email": reviewer_email, "stale": stale,
            "decided": cred.status != "pending"}


@router.get("/email/{token}/certificate")
def email_review_certificate(token: str, db: Session = Depends(get_db)):
    cred, _, _, _ = _read_token(db, token)
    return _certificate_response(cred)


@router.post("/email/{token}/decision")
def email_review_decision(token: str, payload: DecisionIn, db: Session = Depends(get_db)):
    cred, doctor, reviewer_email, stale = _read_token(db, token)
    note = _check_note(payload.decision, payload.note)
    if stale:
        raise HTTPException(status_code=409, detail="The doctor changed their details after this email was sent. "
                                                    "Use the newer email.")
    if cred.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"Already decided: {cred.status} by {cred.reviewer or 'a reviewer'}.")
    if (doctor.email or "").lower() == reviewer_email:
        raise HTTPException(status_code=403, detail="You can't review your own verification.")
    account = db.query(models.User).filter(models.User.email == reviewer_email).first()
    label = f"{account.full_name} ({reviewer_email})" if account else reviewer_email
    # audit needs a user as actor: the reviewer's account if they have one
    apply_decision(db, doctor, cred, payload.decision == "approve", note, label,
                   account.id if account else doctor.id, via="_via_email")
    return _doctor_out(db, doctor)


def _email_rows(info: dict) -> list:
    checks = info["compliance"]["checks"]
    education = "; ".join(
        f"{e['degree']}, {e['institution']}" + (f" ({e['year']})" if e.get("year") else "") for e in info["education"])
    return [
        ("Doctor", f"{info['name']} ({info['email']})"),
        ("Specialization", info["specialty"]),
        ("Hospital / clinic", info["hospital_name"]),
        ("Registration number", info["registration_number"]),
        ("Medical council", info["medical_council"]),
        ("Year of registration", info["registration_year"]),
        ("Qualifications", info["qualification"]),
        ("Education", education),
        ("Experience", f"{info['years_of_experience']} years" if info["years_of_experience"] is not None else ""),
        ("Automatic checks", f"{sum(c['passed'] for c in checks)} of {len(checks)} met"),
    ]


def notify_reviewers(db: Session, doctor: models.User) -> int:
    """Email every reviewer about a new or changed verification request.
    Returns how many emails went out."""
    cred = db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == doctor.id).first()
    if not cred or cred.status != "pending":
        return 0
    info = _doctor_out(db, doctor)
    attachments = []
    if cred.certificate_path:
        try:
            attachments = [(cred.certificate_file_name or "certificate",
                            read_upload(cred.certificate_path), cred.certificate_content_type)]
        except OSError:
            attachments = []
    rows = _email_rows(info)
    table = "".join(
        f"<tr><td style='padding:4px 14px 4px 0;color:#5b6472'>{escape(k)}</td>"
        f"<td style='padding:4px 0'>{escape(str(v or '-'))}</td></tr>" for k, v in rows)
    sent = 0
    for reviewer_email in sorted(reviewer_emails()):
        if reviewer_email == (doctor.email or "").lower():
            continue  # never ask a doctor to review themselves
        base = f"{email_utils.frontend_url()}/review-decision?token={make_review_token(cred, reviewer_email)}"
        approve_url, reject_url = f"{base}&action=approve", f"{base}&action=reject"
        html = (
            "<html><body style='font-family: Arial, sans-serif; color: #1c2733;'>"
            "<h2 style='color:#16365f'>Doctor verification request</h2>"
            f"<p>{escape(info['name'])} submitted their details for verification. Check the registration number "
            f"on the <a href='{NMC_REGISTER}'>Indian Medical Register</a> and the attached certificate, then decide:</p>"
            f"<table>{table}</table>"
            "<p style='margin-top:18px'>"
            f"<a href='{approve_url}' style='background:#3c9d7b;color:#fff;padding:10px 18px;"
            "border-radius:6px;text-decoration:none;'>Approve</a>&nbsp;&nbsp;"
            f"<a href='{reject_url}' style='background:#b3412c;color:#fff;padding:10px 18px;"
            "border-radius:6px;text-decoration:none;'>Reject</a></p>"
            "<p style='color:#5b6472;font-size:13px'>Each button opens a page where you confirm; nothing changes "
            f"until you do. The links work for this request only and expire in {EMAIL_LINK_DAYS} days.</p>"
            "</body></html>"
        )
        text = "\n".join(
            ["Doctor verification request", ""]
            + [f"{k}: {v or '-'}" for k, v in rows]
            + ["", f"Approve: {approve_url}", f"Reject: {reject_url}", "",
               f"Each link opens a page where you confirm. They expire in {EMAIL_LINK_DAYS} days."]
        )
        subject = f"MediPass: verify {info['name']} ({info['registration_number']})"
        if email_utils.send_email(reviewer_email, subject, html, text, attachments):
            sent += 1
    return sent
