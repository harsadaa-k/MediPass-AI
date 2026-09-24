from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/lookup-patient", response_model=schemas.PatientLookupOut)
def lookup_patient(
    email: str,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    """
    Lets a provider find a patient's id from their email so they can send an
    access request. Deliberately returns only id/name/email -- no medical
    data leaks through a lookup (FR-5.3 still applies to everything else).
    """
    patient = (
        db.query(models.User)
        .filter(models.User.email == email, models.User.role == models.UserRole.patient)
        .first()
    )
    if not patient:
        raise HTTPException(status_code=404, detail="No patient found with that email.")
    return patient


@router.get("/badges", response_model=schemas.BadgesOut)
def get_badges(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """
    Returns counts for pending notifications like access requests and unverified records.
    Only applicable to patients.
    """
    if user.role != models.UserRole.patient:
        return schemas.BadgesOut(pending_access_requests=0, unverified_records=0, unread_notifications=0,
                                 pending_links=0)
        
    pending_requests = db.query(models.AccessGrant).filter(
        models.AccessGrant.patient_id == user.id,
        models.AccessGrant.status == models.AccessStatus.pending
    ).count()
    
    unverified_records = db.query(models.MedicalRecord).filter(
        models.MedicalRecord.patient_id == user.id,
        models.MedicalRecord.verification_status == models.VerificationStatus.unverified
    ).count()

    unread_notifications = db.query(models.Notification).filter(
        models.Notification.patient_id == user.id,
        models.Notification.is_read == False
    ).count()
    
    pending_links = db.query(models.RecordLink).filter(
        models.RecordLink.patient_id == user.id,
        models.RecordLink.status == "linked",
    ).count()

    return schemas.BadgesOut(
        pending_access_requests=pending_requests,
        unverified_records=unverified_records,
        unread_notifications=unread_notifications,
        pending_links=pending_links,
    )
