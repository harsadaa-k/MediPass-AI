import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas, auth, linking
from ..database import get_db
from ..serializers import record_to_out
from ..access_control import assert_can_view_patient
from ..llm import structure_voice_transcript

router = APIRouter(prefix="/consultations", tags=["consultations"])


class VoiceTranscriptIn(BaseModel):
    transcript: str


@router.post("", response_model=schemas.MedicalRecordOut, status_code=201)
def add_consultation(
    payload: schemas.ConsultationIn,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    # Reuses the same consent check as viewing -- a provider can only add
    # records for a patient who has approved them (FR-6.1).
    assert_can_view_patient(db, provider, payload.patient_id)

    record = models.MedicalRecord(
        patient_id=payload.patient_id,
        record_type=payload.record_type,
        title=payload.title,
        details=json.dumps(payload.details),
        record_date=payload.record_date,
        source_type=models.SourceType.doctor_generated,
        created_by=provider.id,
        confidence=None,
        verification_status=models.VerificationStatus.provider_verified,
    )
    db.add(record)
    db.add(models.AuditLog(
        patient_id=payload.patient_id, actor_id=provider.id,
        action="record_added", target_type="medical_record",
    ))
    db.flush()  # get record.id for the notification link

    # Link the note to the patient's prescription from this doctor (if any).
    linking.link_consultation(db, record, "consultation added")

    # Notify the patient about the new provider-added record
    name = provider.full_name.strip()
    if not name.lower().startswith("dr"):
        name = f"Dr. {name}"
    record_label = payload.record_type.value.replace("_", " ")
    db.add(models.Notification(
        patient_id=payload.patient_id,
        message=f"{name} added a new {record_label} record: {payload.title}",
        related_record_id=record.id,
    ))
    db.commit()
    db.refresh(record)
    return record_to_out(record)


@router.get("/mine")
def list_my_recent_consultations(
    limit: int = 10,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    """
    Recent records this provider authored, for the provider dashboard.
    Only includes patients the provider *currently* holds an approved,
    unexpired grant for -- revoking access hides these too (FR-5.3).
    """
    now = datetime.utcnow()
    active_patient_ids = [
        g.patient_id
        for g in db.query(models.AccessGrant).filter(
            models.AccessGrant.provider_id == provider.id,
            models.AccessGrant.status == models.AccessStatus.approved,
            or_(models.AccessGrant.expires_at.is_(None), models.AccessGrant.expires_at > now),
        )
    ]
    if not active_patient_ids:
        return []

    rows = (
        db.query(models.MedicalRecord, models.User)
        .join(models.User, models.User.id == models.MedicalRecord.patient_id)
        .filter(
            models.MedicalRecord.created_by == provider.id,
            models.MedicalRecord.patient_id.in_(active_patient_ids),
        )
        .order_by(models.MedicalRecord.created_at.desc())
        .limit(max(1, min(limit, 50)))
        .all()
    )
    return [
        {
            "id": rec.id,
            "patient_id": patient.id,
            "patient_name": patient.full_name,
            "record_type": rec.record_type.value,
            "title": rec.title,
            "record_date": rec.record_date.isoformat(),
        }
        for rec, patient in rows
    ]


@router.post("/voice-structure")
def voice_structure(
    payload: VoiceTranscriptIn,
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    """
    Takes a raw voice transcript and returns AI-structured consultation fields.
    The doctor reviews the result and submits via the normal add_consultation endpoint.
    """
    if not payload.transcript or not payload.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty.")

    current_date = date.today().isoformat()
    result = structure_voice_transcript(payload.transcript.strip(), current_date)
    return result
