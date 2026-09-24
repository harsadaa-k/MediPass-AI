"""
Doctor verification: a provider submits specialization, hospital
affiliation and medical registration details plus a certificate; a reviewer
approves or rejects it (backend/review_doctors.py).

MediPass can't query the National Medical Commission / state council
registers automatically (no public API), so the automated part is limited to
completeness and format checks; the reviewer checks the registration number
against the official register (https://www.nmc.org.in/information-desk/indian-medical-register/)
and the uploaded certificate.

While MEDIPASS_REQUIRE_VERIFIED_DOCTORS is on (default), only verified
doctors can request access to patients or add them by QR code.
"""
import json
import os
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..storage import save_upload, read_upload

router = APIRouter(prefix="/doctor-verification", tags=["doctor-verification"])

REQUIRE_VERIFIED = os.environ.get("MEDIPASS_REQUIRE_VERIFIED_DOCTORS", "true").lower() == "true"
MAX_CERT_BYTES = 10 * 1024 * 1024
CERT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
_REG_NO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-. ]{2,24}$")


def credential_for(db: Session, provider_id: str) -> Optional[models.DoctorCredential]:
    return db.query(models.DoctorCredential).filter(models.DoctorCredential.provider_id == provider_id).first()


def is_verified(db: Session, provider_id: str) -> bool:
    cred = credential_for(db, provider_id)
    return bool(cred and cred.status == "verified")


def require_verified_doctor(db: Session, provider: models.User) -> None:
    """Call before a provider gains access to a new patient."""
    if REQUIRE_VERIFIED and not is_verified(db, provider.id):
        raise HTTPException(
            status_code=403,
            detail="Your doctor profile isn't verified yet. Submit your registration details in "
                   "My Profile; you can add patients once it's approved.",
        )


def _json_list(value: Optional[str]) -> list:
    try:
        parsed = json.loads(value) if value else []
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def years_of_experience(cred: Optional[models.DoctorCredential], today: Optional[date] = None) -> Optional[int]:
    """Whole years since the doctor started practising (or, if not given,
    registered). Only the year is known, so this counts calendar years."""
    since = cred and (cred.practice_start_year or cred.registration_year)
    if not since:
        return None
    return max(0, (today or date.today()).year - since)


def _out(db: Session, provider: models.User) -> dict:
    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == provider.id).first()
    cred = credential_for(db, provider.id)
    return {
        "full_name": provider.full_name,
        "specialty": profile.specialty if profile else None,
        "hospital_name": profile.hospital_name if profile else None,
        "status": cred.status if cred else "not_submitted",
        "registration_number": cred.registration_number if cred else None,
        "medical_council": cred.medical_council if cred else None,
        "qualification": cred.qualification if cred else None,
        "registration_year": cred.registration_year if cred else None,
        "education": _json_list(cred.education) if cred else [],
        "affiliations": _json_list(cred.affiliations) if cred else [],
        "practice_start_year": cred.practice_start_year if cred else None,
        "years_of_experience": years_of_experience(cred),
        "certificate_file_name": cred.certificate_file_name if cred else None,
        "submitted_at": cred.submitted_at if cred else None,
        "reviewed_at": cred.reviewed_at if cred else None,
        "review_note": cred.review_note if cred else None,
        "verification_required": REQUIRE_VERIFIED,
    }


def _clean_education(raw: Optional[str]) -> list:
    """Validate the education list: each entry needs a degree and an
    institution; the year is optional but must be plausible."""
    rows = []
    for item in _json_list(raw) if raw else []:
        if not isinstance(item, dict):
            continue
        degree = str(item.get("degree") or "").strip()
        institution = str(item.get("institution") or "").strip()
        year = item.get("year")
        if not degree and not institution:
            continue  # empty row left in the form
        if len(degree) < 2 or len(institution) < 2:
            raise HTTPException(status_code=400, detail="Each education entry needs a degree and an institution.")
        if year in ("", None):
            year = None
        else:
            try:
                year = int(year)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Year for {degree} looks wrong.")
            if not 1950 <= year <= date.today().year:
                raise HTTPException(status_code=400, detail=f"Year for {degree} looks wrong.")
        rows.append({"degree": degree[:80], "institution": institution[:120], "year": year})
    if raw and not _json_list(raw) and raw.strip() not in ("", "[]"):
        raise HTTPException(status_code=400, detail="Education list couldn't be read.")
    return rows[:10]


def _clean_affiliations(raw: Optional[str], primary: str) -> list:
    names = []
    for item in _json_list(raw) if raw else []:
        name = str(item or "").strip()
        if len(name) >= 2 and name.lower() != (primary or "").strip().lower() and name not in names:
            names.append(name[:120])
    return names[:10]


@router.get("/me")
def my_verification(
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    return _out(db, provider)


@router.post("")
async def submit_verification(
    specialty: str = Form(...),
    hospital_name: str = Form(...),
    registration_number: str = Form(...),
    medical_council: str = Form(...),
    qualification: str = Form(...),
    registration_year: Optional[int] = Form(None),
    practice_start_year: Optional[int] = Form(None),
    education: Optional[str] = Form(None),      # JSON list of {degree, institution, year}
    affiliations: Optional[str] = Form(None),   # JSON list of names
    certificate: Optional[UploadFile] = File(None),
    background: BackgroundTasks = None,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    fields = {
        "Specialization": specialty, "Hospital affiliation": hospital_name,
        "Medical council": medical_council, "Qualification": qualification,
    }
    missing = [k for k, v in fields.items() if len((v or "").strip()) < 2]
    if missing:
        raise HTTPException(status_code=400, detail=f"Please fill in: {', '.join(missing)}.")
    reg_no = registration_number.strip()
    if not _REG_NO.match(reg_no):
        raise HTTPException(status_code=400, detail="Registration number should be 3-25 letters/digits (e.g. KMC 12345).")
    if registration_year is not None and not 1950 <= registration_year <= date.today().year:
        raise HTTPException(status_code=400, detail="Registration year looks wrong.")
    if practice_start_year is not None and not 1950 <= practice_start_year <= date.today().year:
        raise HTTPException(status_code=400, detail="'Practising since' year looks wrong.")
    education_rows = _clean_education(education)
    affiliation_rows = _clean_affiliations(affiliations, hospital_name)

    cred = credential_for(db, provider.id)
    cert_bytes = await certificate.read() if certificate else b""
    if not cert_bytes and not (cred and cred.certificate_path):
        raise HTTPException(status_code=400, detail="Please upload your registration or degree certificate.")
    if cert_bytes:
        if len(cert_bytes) > MAX_CERT_BYTES:
            raise HTTPException(status_code=413, detail="Certificate file is too large (10 MB max).")
        if (certificate.content_type or "") not in CERT_TYPES:
            raise HTTPException(status_code=400, detail="Upload the certificate as a PDF, JPEG, PNG or WEBP.")

    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == provider.id).first()
    if not profile:
        profile = models.ProviderProfile(user_id=provider.id)
        db.add(profile)
    profile.specialty = specialty.strip()
    profile.hospital_name = hospital_name.strip()

    if not cred:
        cred = models.DoctorCredential(provider_id=provider.id)
        db.add(cred)
    cred.registration_number = reg_no
    cred.medical_council = medical_council.strip()
    cred.qualification = qualification.strip()
    cred.registration_year = registration_year
    cred.practice_start_year = practice_start_year
    cred.education = json.dumps(education_rows)
    cred.affiliations = json.dumps(affiliation_rows)
    if cert_bytes:
        cred.certificate_path = save_upload(provider.id, certificate.filename or "certificate", cert_bytes)
        cred.certificate_file_name = certificate.filename or "certificate"
        cred.certificate_content_type = certificate.content_type
    # Any change goes back to review -- the reviewed details must match what's shown.
    cred.status = "pending"
    cred.submitted_at = datetime.utcnow()
    cred.reviewed_at = None
    cred.reviewer = None
    cred.review_note = None
    db.commit()
    # Email the reviewers (details, certificate, Approve / Reject links)
    # after the response, so the doctor isn't kept waiting on SMTP.
    if background is not None:
        background.add_task(_email_reviewers, provider.id)
    return _out(db, provider)


def _email_reviewers(provider_id: str) -> None:
    from ..database import SessionLocal
    from .reviewer import notify_reviewers
    db = SessionLocal()
    try:
        doctor = db.query(models.User).filter(models.User.id == provider_id).first()
        if doctor:
            notify_reviewers(db, doctor)
    except Exception as e:  # never break the submission over an email
        print(f"Reviewer email failed: {type(e).__name__}: {e}")
    finally:
        db.close()


@router.get("/certificate")
def my_certificate(
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    cred = credential_for(db, provider.id)
    if not cred or not cred.certificate_path:
        raise HTTPException(status_code=404, detail="No certificate uploaded.")
    return Response(content=read_upload(cred.certificate_path),
                    media_type=cred.certificate_content_type or "application/octet-stream")


# ---------- verification document ----------

_COUNCIL = re.compile(r"(national medical commission|\bnmc\b|medical council|medical councils|dental council|council of (indian|homoeopathy)|\bmci\b)", re.I)
# Primary qualifications that allow registration with a medical/dental council in India
_PRIMARY_DEGREE = re.compile(r"\b(M\.?B\.?B\.?S|B\.?D\.?S|B\.?A\.?M\.?S|B\.?H\.?M\.?S|B\.?U\.?M\.?S|M\.?D|M\.?S|D\.?N\.?B|D\.?M|M\.?Ch|MRCP|FRCS)\b", re.I)
AUTHORITY = ("MediPass credential review: registration checked by a reviewer against the "
             "Indian Medical Register (National Medical Commission) or the state medical council register")


def compliance_checks(cred: Optional[models.DoctorCredential], profile) -> list:
    """What the medical-board requirements need, and whether we have it.
    `required` checks must all pass for 'Compliant'."""
    edu = _json_list(cred.education) if cred else []
    reviewed_current = bool(cred and cred.status == "verified" and cred.reviewed_at
                            and cred.submitted_at and cred.reviewed_at >= cred.submitted_at)
    return [
        {"label": "Registered with a recognised medical council",
         "passed": bool(cred and _COUNCIL.search(cred.medical_council or "")), "required": True,
         "detail": (cred.medical_council if cred else None) or "No council given"},
        {"label": "Registration number in a valid format",
         "passed": bool(cred and _REG_NO.match(cred.registration_number or "")), "required": True,
         "detail": (cred.registration_number if cred else None) or "Not given"},
        {"label": "Recognised medical qualification (MBBS or equivalent)",
         "passed": bool(cred and _PRIMARY_DEGREE.search(" ".join(
             [cred.qualification or ""] + [e.get("degree", "") for e in edu]))), "required": True,
         "detail": (cred.qualification if cred else None) or "Not given"},
        {"label": "Registration or degree certificate on file",
         "passed": bool(cred and cred.certificate_path), "required": True,
         "detail": (cred.certificate_file_name if cred else None) or "No certificate uploaded"},
        {"label": "Specialization and hospital affiliation declared",
         "passed": bool(profile and profile.specialty and profile.hospital_name), "required": True,
         "detail": ", ".join(x for x in [profile and profile.specialty, profile and profile.hospital_name] if x) or "Not given"},
        {"label": "Registration checked against the official register by a reviewer",
         "passed": reviewed_current, "required": True, "key": "reviewed",
         "detail": {"verified": "Approved", "pending": "Waiting for review",
                    "rejected": f"Not approved: {cred.review_note or 'no reason given'}" if cred else ""}.get(
                        cred.status if cred else "", "Not submitted")},
        {"label": "Education history provided",
         "passed": bool(edu), "required": False,
         "detail": f"{len(edu)} entr{'y' if len(edu) == 1 else 'ies'}" if edu else "Recommended: add degrees and institutions"},
    ]


def overall_compliance(cred, checks) -> str:
    if not cred:
        return "Not submitted"
    details_ok = all(c["passed"] for c in checks if c["required"] and c.get("key") != "reviewed")
    if cred.status == "rejected" or not details_ok:
        return "Not compliant"
    if cred.status != "verified":
        return "Pending review"
    reviewed = next(c for c in checks if c.get("key") == "reviewed")
    return "Compliant" if reviewed["passed"] else "Pending review"


def verification_document(db: Session, provider: models.User) -> dict:
    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == provider.id).first()
    cred = credential_for(db, provider.id)
    checks = compliance_checks(cred, profile)
    info = _out(db, provider)
    return {
        "document_id": f"MPV-{cred.id[:8].upper()}" if cred else None,
        "generated_at": datetime.utcnow(),
        "doctor": {"name": provider.full_name, "email": provider.email},
        "status": info["status"],
        "credentials": {
            "registration_number": info["registration_number"],
            "medical_council": info["medical_council"],
            "registration_year": info["registration_year"],
            "qualification": info["qualification"],
            "certificate_file_name": info["certificate_file_name"],
            "license_status": {"verified": "Verified", "pending": "Under review",
                               "rejected": "Not approved"}.get(info["status"], "Not submitted"),
        },
        "education": info["education"],
        "affiliations": {"primary": info["hospital_name"], "other": info["affiliations"]},
        "specialization": info["specialty"],
        "experience": {
            "since": (cred.practice_start_year or cred.registration_year) if cred else None,
            "since_basis": ("practice start" if cred and cred.practice_start_year
                            else "registration year" if cred and cred.registration_year else None),
            "years": info["years_of_experience"],
        },
        "verification": {
            "submitted_at": info["submitted_at"],
            "reviewed_at": info["reviewed_at"],
            "reviewer": cred.reviewer if cred else None,
            "review_note": info["review_note"],
            "authority": AUTHORITY,
        },
        "compliance": {"overall": overall_compliance(cred, checks), "checks": checks},
    }


@router.get("/document")
def my_verification_document(
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    """Structured verification document for the doctor's profile (the
    frontend renders it as a printable page)."""
    return verification_document(db, provider)
