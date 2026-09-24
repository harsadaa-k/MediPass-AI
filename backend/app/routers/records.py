import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth, imaging, duplicates
from ..database import get_db
from ..serializers import record_to_out

router = APIRouter(prefix="/records", tags=["records"])


@router.get("/body-parts")
def list_body_parts(user: models.User = Depends(auth.get_current_user)):
    """Anatomical regions the verify screen offers for imaging records."""
    return [{"code": c, "label": l} for c, l in imaging.BODY_PARTS.items() if c != "unknown"]


@router.get("/unverified", response_model=list[schemas.MedicalRecordOut])
def list_unverified(
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    records = (
        db.query(models.MedicalRecord)
        .filter(
            models.MedicalRecord.patient_id == patient.id,
            models.MedicalRecord.verification_status == models.VerificationStatus.unverified,
        )
        .all()
    )
    # Flag entries that repeat something already on the timeline (same
    # prescription uploaded again as a different photo).
    pool = duplicates.timeline_records(db, patient.id)
    out = []
    for r in records:
        item = record_to_out(r)
        dup = duplicates.find_duplicate_of(r, pool)
        if dup:
            item.duplicate_of = {"id": dup.id, "title": dup.title, "record_date": dup.record_date.isoformat(),
                                 "logged_at": dup.created_at.isoformat() if dup.created_at else None}
        out.append(item)
    return out


@router.post("/{record_id}/verify", response_model=schemas.MedicalRecordOut)
def verify_record(
    record_id: str,
    payload: schemas.RecordVerifyIn,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    record = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    if record.patient_id != patient.id:
        raise HTTPException(status_code=403, detail="Not your record.")

    original_details = json.loads(record.details) if record.details else {}
    if payload.corrected_details is not None:
        record.details = json.dumps(payload.corrected_details)
    if payload.corrected_title is not None:
        record.title = payload.corrected_title
    if payload.corrected_record_date is not None:
        if payload.corrected_record_date > date.today():
            raise HTTPException(status_code=400, detail="The consultation date can't be in the future.")
        record.record_date = payload.corrected_record_date
        # the patient supplied the real date, so it's no longer a stand-in
        d = json.loads(record.details) if record.details else {}
        if isinstance(d, dict) and d.pop("is_fallback_date", None) is not None:
            record.details = json.dumps(d)

    # Imaging records: the body part must be a known region and is stored as
    # patient-confirmed -- the AI/DICOM value is only ever a suggestion.
    details = json.loads(record.details) if record.details else {}
    if isinstance(details, dict) and "body_part" in details:
        part = imaging.normalize_body_part(details.get("body_part"))
        if part == "unknown":
            raise HTTPException(
                status_code=400,
                detail="Choose which body part this image shows before confirming it.",
            )
        if original_details.get("body_part_source") != "patient_confirmed":
            # keep what the system suggested, for traceability
            details["body_part_suggested"] = original_details.get("body_part")
            details["body_part_suggested_by"] = original_details.get("body_part_source")
        details.update({
            "body_part": part,
            "body_part_label": imaging.BODY_PARTS[part],
            "body_part_source": "patient_confirmed",
        })
        details.pop("body_part_note", None)
        record.details = json.dumps(details)
        record.title = imaging.imaging_title(details.get("modality", "xray"), part, details.get("laterality", ""))

    record.verification_status = models.VerificationStatus.patient_verified
    db.commit()
    db.refresh(record)
    return record_to_out(record)


@router.delete("/{record_id}", status_code=204)
def delete_record(
    record_id: str,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    record = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    if record.patient_id != patient.id:
        raise HTTPException(status_code=403, detail="Not your record.")

    link = db.query(models.RecordLink).filter(models.RecordLink.consultation_id == record.id).first()
    if link and link.status == "confirmed":
        raise HTTPException(status_code=409, detail="This note is part of a link you confirmed, so it can't be removed.")
    if link:
        db.delete(link)
    db.delete(record)
    db.commit()
    return
