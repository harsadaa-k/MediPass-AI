"""
Active Patients list for the doctor's dashboard: each patient the doctor
currently has access to, with a status and key metrics.

Status (first rule that applies):
  1. set by the doctor          -> that status ("Set by you")
  2. critical                   -> a record the doctor can see, dated in the
                                   last 90 days, mentions an urgent/critical
                                   finding (e.g. "urgent referral",
                                   "high suicidal risk")
  3. follow_up                  -> the doctor's latest note gives a follow-up
                                   date ("review after 2 weeks") that has arrived
  4. new                        -> access granted in the last 7 days and no
                                   note from this doctor yet
  5. ongoing                    -> everything else

Day counts use calendar dates (app/durations.py). Only records inside the
patient's sharing scope are read, same as the timeline.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..durations import follow_up_due

router = APIRouter(prefix="/provider/patients", tags=["provider-patients"])

STATUSES = ("new", "ongoing", "critical", "follow_up")
NEW_DAYS = 7
CRITICAL_LOOKBACK_DAYS = 90
_CRITICAL = re.compile(
    r"\b(urgent\w*|critical\w*|emergency|suicid\w*|high[- ]risk|icu|intensive care|"
    r"inpatient care|admit(?:ted)? immediately|life[- ]threatening|anaphyla\w*|sepsis|stroke|"
    r"myocardial infarction|heart attack)\b",
    re.I,
)
_SCOPE_TYPES = {
    "medications": models.RecordType.medication,
    "labs": models.RecordType.lab_result,
    "allergies": models.RecordType.allergy,
    "diagnoses": models.RecordType.diagnosis,
}


def _visible_records(db: Session, grant: models.AccessGrant, provider_id: str) -> list:
    """Records this doctor may see (same rule as the timeline), plus their own notes."""
    scope = json.loads(grant.scope or "[]")
    query = db.query(models.MedicalRecord).filter(
        models.MedicalRecord.patient_id == grant.patient_id,
        ~((models.MedicalRecord.source_type == models.SourceType.ai_extracted)
          & (models.MedicalRecord.verification_status == models.VerificationStatus.unverified)),
    )
    if "full_history" not in scope:
        allowed = [_SCOPE_TYPES[s] for s in scope if s in _SCOPE_TYPES]
        records = query.filter(models.MedicalRecord.record_type.in_(allowed)).all() if allowed else []
        own = query.filter(models.MedicalRecord.created_by == provider_id).all()
        seen = {r.id for r in records}
        records += [r for r in own if r.id not in seen]
        return records
    return query.all()


def _local_date(utc: datetime) -> date:
    """Timestamps are stored as naive UTC; day counts use the local calendar."""
    return utc.replace(tzinfo=timezone.utc).astimezone().date()


def _text_of(record: models.MedicalRecord) -> str:
    try:
        details = json.loads(record.details or "{}")
    except ValueError:
        details = {}
    if not isinstance(details, dict):
        details = {"text": str(details)}
    parts = [record.title] + [str(details.get(k) or "") for k in ("text", "notes", "follow_up")]
    return " ".join(p for p in parts if p)


def _snippet(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 40)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _patient_row(db: Session, grant: models.AccessGrant, provider: models.User,
                 flag: Optional[models.PatientStatusFlag], today: date) -> dict:
    patient = db.query(models.User).filter(models.User.id == grant.patient_id).first()
    records = _visible_records(db, grant, provider.id)
    own_notes = sorted(
        (r for r in records if r.created_by == provider.id),
        key=lambda r: (r.record_date, r.created_at or datetime.min),
    )
    last_note = own_notes[-1] if own_notes else None
    granted_at = grant.responded_at or grant.requested_at
    granted_on = _local_date(granted_at) if granted_at else today

    follow_up_on = follow_up_due(_text_of(last_note), last_note.record_date) if last_note else None

    critical_reason = None
    since = today - timedelta(days=CRITICAL_LOOKBACK_DAYS)
    for r in sorted(records, key=lambda r: r.record_date, reverse=True):
        if r.record_date < since:
            break
        text = _text_of(r)
        m = _CRITICAL.search(text)
        if m:
            critical_reason = f"{r.record_date.isoformat()}: {_snippet(text, m)}"
            break

    if flag:
        status, reason = flag.status, f"Set by you{': ' + flag.note if flag.note else ''}"
    elif critical_reason:
        status, reason = "critical", critical_reason
    elif follow_up_on and follow_up_on <= today:
        status, reason = "follow_up", f"Follow-up was due {follow_up_on.isoformat()}"
    elif (today - granted_on).days < NEW_DAYS and not own_notes:
        status, reason = "new", f"Access granted {granted_on.isoformat()}, no consultation yet"
    else:
        status, reason = "ongoing", (f"Last consultation {last_note.record_date.isoformat()}"
                                     if last_note else "Under your care")

    return {
        "grant_id": grant.id,
        "patient_id": grant.patient_id,
        "patient_name": patient.full_name if patient else None,
        "patient_email": patient.email if patient else None,
        "scope": json.loads(grant.scope or "[]"),
        "status": status,
        "status_reason": reason,
        "status_set_by_doctor": bool(flag),
        "granted_at": granted_at,
        "expires_at": grant.expires_at,
        "days_under_care": (today - granted_on).days,
        "last_visit": last_note.record_date if last_note else None,
        "days_since_last_visit": (today - last_note.record_date).days if last_note else None,
        "consultations": len(own_notes),
        "records_shared": len(records),
        "follow_up_due": follow_up_on,
        "days_until_access_expires": (_local_date(grant.expires_at) - today).days if grant.expires_at else None,
    }


@router.get("")
def list_patients(
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    now = datetime.utcnow()
    today = date.today()  # local calendar day, like the dates written on records
    grants = (
        db.query(models.AccessGrant)
        .filter(models.AccessGrant.provider_id == provider.id,
                models.AccessGrant.status.in_([models.AccessStatus.approved, models.AccessStatus.revoked]))
        .order_by(models.AccessGrant.requested_at.desc())
        .all()
    )
    flags = {f.patient_id: f for f in db.query(models.PatientStatusFlag)
             .filter(models.PatientStatusFlag.provider_id == provider.id)}

    def is_active(g):
        return g.status == models.AccessStatus.approved and (g.expires_at is None or g.expires_at > now)

    # One row per patient: an active grant wins, otherwise the newest ended one.
    active, inactive, seen = [], [], set()
    for g in sorted(grants, key=lambda g: not is_active(g)):
        if g.patient_id in seen:
            continue
        seen.add(g.patient_id)
        if is_active(g):
            active.append(_patient_row(db, g, provider, flags.get(g.patient_id), today))
        else:
            expired = g.expires_at is not None and g.expires_at <= now
            patient = db.query(models.User).filter(models.User.id == g.patient_id).first()
            inactive.append({
                "patient_id": g.patient_id,
                "patient_name": patient.full_name if patient else None,
                "patient_email": patient.email if patient else None,
                "reason": "expired" if expired else "revoked",
                "expired_at": g.expires_at if expired else None,
            })
    counts = {s: sum(1 for p in active if p["status"] == s) for s in STATUSES}
    return {"generated_at": now, "total_active": len(active), "counts": counts,
            "active": active, "inactive": inactive}


class StatusIn(BaseModel):
    status: Optional[str] = None  # None = back to automatic
    note: Optional[str] = None


@router.put("/{patient_id}/status")
def set_status(
    patient_id: str,
    payload: StatusIn,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    from ..access_control import assert_can_view_patient
    assert_can_view_patient(db, provider, patient_id)
    if payload.status is not None and payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {', '.join(STATUSES)}.")
    flag = (db.query(models.PatientStatusFlag)
            .filter(models.PatientStatusFlag.provider_id == provider.id,
                    models.PatientStatusFlag.patient_id == patient_id).first())
    if payload.status is None:
        if flag:
            db.delete(flag)
    else:
        if not flag:
            flag = models.PatientStatusFlag(provider_id=provider.id, patient_id=patient_id, status=payload.status)
            db.add(flag)
        flag.status = payload.status
        flag.note = (payload.note or "").strip()[:200] or None
        flag.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}
