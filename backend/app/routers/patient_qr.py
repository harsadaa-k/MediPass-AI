"""
Patient QR codes: the patient shows a QR code, a doctor scans it, and the
patient is added to the doctor's patient list immediately.

Consent model: generating the code (and choosing what it shares and for how
long) is the patient's consent, given in person. So redeeming it creates an
*approved* access grant directly -- there is no access request for the
patient to approve afterwards. Safeguards instead of an approval step:
  * if the doctor already has active access, nothing about that access
    changes -- the doctor is told the patient already exists
  * the code carries a 256-bit random token; only its SHA-256 hash is stored
  * a short code (8 characters, e.g. K7Q4-M9TX) is shown above the QR for
    doctors to type in; same rules, also stored only as a hash, and a doctor
    who keeps typing wrong codes is paused (brute-force guard)
  * single use, and only scannable for a short window (default 15 minutes)
  * limited to the scope and access period the patient picked
  * creating a new code invalidates the patient's previous unused codes
  * every scan is written to the patient's audit log, the patient gets an
    informational notification, and can revoke the doctor's access anytime
"""
import hashlib
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from .doctor_verification import require_verified_doctor

router = APIRouter(prefix="/patient-qr", tags=["patient-qr"])

ALLOWED_SCOPES = {"medications", "labs", "allergies", "diagnoses", "full_history"}
_TOKEN_RE = re.compile(r"(?:/add-patient/)?([A-Za-z0-9_-]{32,})/?$")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Short code: no 0/O, 1/I/L, so it reads out and types without mix-ups.
# 31^8 (~8.5e11) combinations, live for minutes and single use.
SHORT_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
SHORT_CODE_LEN = 8
_SHORT_RE = re.compile(rf"^[{SHORT_CODE_ALPHABET}]{{{SHORT_CODE_LEN}}}$")

# Brute-force guard: wrong codes per doctor within the window.
MAX_BAD_CODES = 10
BAD_CODE_WINDOW_S = 15 * 60
_bad_codes: dict[str, deque] = defaultdict(deque)
_bad_codes_lock = threading.Lock()


def _normalize_short(code: str) -> str:
    return re.sub(r"[\s-]", "", code).upper()


def _short_hash(code: str) -> str:
    return _hash("short:" + _normalize_short(code))


def _format_short(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _recent_bad_codes(provider_id: str) -> deque:
    q = _bad_codes[provider_id]
    cutoff = time.monotonic() - BAD_CODE_WINDOW_S
    while q and q[0] < cutoff:
        q.popleft()
    return q


def _to_out(db: Session, qr: models.PatientQRCode, token: str | None = None) -> schemas.PatientQROut:
    used_by = db.query(models.User).filter(models.User.id == qr.used_by).first() if qr.used_by else None
    outcome = None
    if qr.used_at:
        existing = db.query(models.AuditLog).filter(
            models.AuditLog.action == "qr_scanned_existing_patient",
            models.AuditLog.target_id == qr.id,
        ).first()
        outcome = "already_patient" if existing else "added"
    return schemas.PatientQROut(
        id=qr.id, token=token, scope=json.loads(qr.scope), access_days=qr.access_days,
        created_at=qr.created_at, expires_at=qr.expires_at, used_at=qr.used_at,
        used_by_name=used_by.full_name if used_by else None, revoked=qr.revoked, outcome=outcome,
    )


@router.post("", response_model=schemas.PatientQROut, status_code=201)
def create_qr(
    payload: schemas.PatientQRCreateIn,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    scope = [s for s in dict.fromkeys(payload.scope) if s in ALLOWED_SCOPES]
    if not scope:
        raise HTTPException(status_code=400, detail="Choose at least one thing to share.")
    if not 1 <= payload.access_days <= 365:
        raise HTTPException(status_code=400, detail="Access period must be between 1 and 365 days.")
    if not 5 <= payload.valid_minutes <= 24 * 60:
        raise HTTPException(status_code=400, detail="QR validity must be between 5 minutes and 24 hours.")

    now = datetime.utcnow()
    # Only one live code at a time: showing a new one cancels older ones.
    db.query(models.PatientQRCode).filter(
        models.PatientQRCode.patient_id == patient.id,
        models.PatientQRCode.used_at.is_(None),
        models.PatientQRCode.revoked.is_(False),
    ).update({models.PatientQRCode.revoked: True})

    token = secrets.token_urlsafe(32)
    # A short code no other live code is using, so typing it finds one patient.
    while True:
        short = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LEN))
        clash = db.query(models.PatientQRCode).filter(
            models.PatientQRCode.short_code_hash == _short_hash(short),
            models.PatientQRCode.used_at.is_(None),
            models.PatientQRCode.revoked.is_(False),
            models.PatientQRCode.expires_at > now,
        ).first()
        if not clash:
            break
    qr = models.PatientQRCode(
        patient_id=patient.id, token_hash=_hash(token), short_code_hash=_short_hash(short), scope=json.dumps(scope),
        access_days=payload.access_days, expires_at=now + timedelta(minutes=payload.valid_minutes),
    )
    db.add(qr)
    db.flush()
    db.add(models.AuditLog(patient_id=patient.id, actor_id=patient.id, action="qr_code_created",
                           target_type="patient_qr", target_id=qr.id))
    db.commit()
    db.refresh(qr)
    out = _to_out(db, qr, token=token)
    out.short_code = _format_short(short)
    return out


@router.get("/{qr_id}", response_model=schemas.PatientQROut)
def get_qr(
    qr_id: str,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    """Lets the patient's screen see when the code has been scanned."""
    qr = db.query(models.PatientQRCode).filter(
        models.PatientQRCode.id == qr_id, models.PatientQRCode.patient_id == patient.id
    ).first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found.")
    return _to_out(db, qr)


@router.post("/{qr_id}/revoke", response_model=schemas.PatientQROut)
def revoke_qr(
    qr_id: str,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    qr = db.query(models.PatientQRCode).filter(
        models.PatientQRCode.id == qr_id, models.PatientQRCode.patient_id == patient.id
    ).first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found.")
    qr.revoked = True
    db.commit()
    db.refresh(qr)
    return _to_out(db, qr)


@router.post("/redeem", response_model=schemas.PatientQRRedeemOut)
def redeem_qr(
    payload: schemas.PatientQRRedeemIn,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    """Doctor scanned a patient's QR code (or typed its short code): add the patient immediately."""
    with _bad_codes_lock:
        if len(_recent_bad_codes(provider.id)) >= MAX_BAD_CODES:
            raise HTTPException(status_code=429, detail="Too many wrong codes. Wait 15 minutes, or scan the patient's QR code.")
    code = payload.code.strip()
    m = _TOKEN_RE.search(code)
    qr = None
    if m:
        qr = db.query(models.PatientQRCode).filter(models.PatientQRCode.token_hash == _hash(m.group(1))).first()
    elif _SHORT_RE.match(_normalize_short(code)):
        # An old code may share the hash; prefer the one that's still usable.
        matches = (
            db.query(models.PatientQRCode)
            .filter(models.PatientQRCode.short_code_hash == _short_hash(code))
            .order_by(models.PatientQRCode.created_at.desc())
            .all()
        )
        now = datetime.utcnow()
        qr = next((q for q in matches if not q.used_at and not q.revoked and q.expires_at > now),
                  matches[0] if matches else None)
    if not qr:
        with _bad_codes_lock:
            _recent_bad_codes(provider.id).append(time.monotonic())
        raise HTTPException(status_code=404, detail="This isn't a valid MediPass patient code. Check it and try again.")

    now = datetime.utcnow()
    if qr.revoked:
        raise HTTPException(status_code=410, detail="This QR code was cancelled by the patient. Ask them to show a new one.")
    if qr.used_at:
        raise HTTPException(status_code=410, detail="This QR code has already been used. Ask the patient to show a new one.")
    if now > qr.expires_at:
        raise HTTPException(status_code=410, detail="This QR code has expired. Ask the patient to show a new one.")

    patient = db.query(models.User).filter(models.User.id == qr.patient_id).first()

    # Reuse the doctor's existing grant for this patient if there is one
    # (pending request, active, expired or revoked) so the patient's access
    # list shows one row per doctor.
    grant = (
        db.query(models.AccessGrant)
        .filter(models.AccessGrant.patient_id == patient.id, models.AccessGrant.provider_id == provider.id)
        .order_by(models.AccessGrant.requested_at.desc())
        .first()
    )
    already_had_access = bool(
        grant and grant.status == models.AccessStatus.approved
        and (grant.expires_at is None or grant.expires_at > now)
    )
    name = provider.full_name.strip()
    if not name.lower().startswith("dr"):
        name = f"Dr. {name}"

    if already_had_access:
        # Already this doctor's active patient: leave the existing grant
        # (scope, dates) exactly as it is. The code is still consumed so it
        # can't be passed on, and the patient's screen shows what happened.
        qr.used_at = now
        qr.used_by = provider.id
        current = json.loads(grant.scope)
        db.add(models.AuditLog(patient_id=patient.id, actor_id=provider.id, action="qr_scanned_existing_patient",
                               target_type="patient_qr", target_id=qr.id))
        db.add(models.Notification(
            patient_id=patient.id,
            message=(f"{name} scanned your QR code. You're already their patient, so nothing changed "
                     f"(they can see your {', '.join(current).replace('_', ' ')}"
                     f"{' until ' + grant.expires_at.strftime('%d %b %Y') if grant.expires_at else ''})."),
        ))
        db.commit()
        return schemas.PatientQRRedeemOut(
            grant_id=grant.id, patient_id=patient.id, patient_name=patient.full_name,
            patient_email=patient.email, scope=current, expires_at=grant.expires_at,
            already_had_access=True,
        )

    require_verified_doctor(db, provider)
    if not grant:
        grant = models.AccessGrant(patient_id=patient.id, provider_id=provider.id, requested_at=now)
        db.add(grant)
    grant.status = models.AccessStatus.approved
    grant.scope = qr.scope
    grant.responded_at = now
    grant.expires_at = now + timedelta(days=qr.access_days)

    qr.used_at = now
    qr.used_by = provider.id
    db.flush()

    scope = json.loads(qr.scope)
    db.add(models.AuditLog(patient_id=patient.id, actor_id=provider.id, action="access_granted_via_qr",
                           target_type="access_grant", target_id=grant.id))
    db.add(models.Notification(
        patient_id=patient.id,
        message=(f"{name} scanned your QR code and can now see your {', '.join(scope).replace('_', ' ')} "
                 f"for {qr.access_days} days. You can revoke this anytime in Access requests."),
    ))
    db.commit()
    db.refresh(grant)

    return schemas.PatientQRRedeemOut(
        grant_id=grant.id, patient_id=patient.id, patient_name=patient.full_name,
        patient_email=patient.email, scope=scope, expires_at=grant.expires_at,
        already_had_access=False,
    )
