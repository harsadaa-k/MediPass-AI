"""
Reviewer screen API: approve or reject doctor verification requests from the
app instead of the review_doctors.py command line.

Who is a reviewer: any logged-in account whose email is listed in
MEDIPASS_REVIEWER_EMAILS (comma-separated). No new role is needed, and it
works on Railway by setting that one variable. A reviewer can't decide on
their own verification. Every decision is stored on the credential
(reviewer, time, note), audited, and the doctor is notified -- the same as
the CLI.
"""
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..storage import read_upload
from .doctor_verification import _json_list, compliance_checks, overall_compliance, years_of_experience

router = APIRouter(prefix="/reviewer", tags=["reviewer"])

STATUSES = ("pending", "verified", "rejected", "not_submitted")


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
    if not cred or not cred.certificate_path:
        raise HTTPException(status_code=404, detail="No certificate uploaded.")
    try:
        content = read_upload(cred.certificate_path)
    except OSError:
        raise HTTPException(status_code=404, detail="The certificate file is missing on the server.")
    return Response(content=content, media_type=cred.certificate_content_type or "application/octet-stream")


class DecisionIn(BaseModel):
    decision: str            # "approve" | "reject"
    note: Optional[str] = None


@router.post("/doctors/{doctor_id}/decision")
def decide(
    doctor_id: str,
    payload: DecisionIn,
    db: Session = Depends(get_db),
    reviewer: models.User = Depends(require_reviewer),
):
    if payload.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'.")
    if doctor_id == reviewer.id:
        raise HTTPException(status_code=403, detail="You can't review your own verification.")
    doctor = db.query(models.User).filter(models.User.id == doctor_id,
                                          models.User.role == models.UserRole.provider).first()
    cred = doctor and db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == doctor.id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="This doctor hasn't submitted verification details.")
    note = (payload.note or "").strip()[:500]
    if payload.decision == "reject" and len(note) < 5:
        raise HTTPException(status_code=400, detail="Give the doctor a reason (at least 5 characters).")

    approve = payload.decision == "approve"
    cred.status = "verified" if approve else "rejected"
    cred.reviewed_at = datetime.utcnow()
    cred.reviewer = _reviewer_label(reviewer)
    cred.review_note = note or None
    db.add(models.Notification(
        patient_id=doctor.id,  # notifications are per user; the doctor sees it in their account
        message=("Your doctor profile has been verified." if approve
                 else f"Your doctor verification was not approved: {note}"),
    ))
    db.add(models.AuditLog(
        patient_id=doctor.id, actor_id=reviewer.id,
        action="doctor_verification_approved" if approve else "doctor_verification_rejected",
        target_type="doctor_credential", target_id=cred.id,
    ))
    db.commit()
    return _doctor_out(db, doctor)
