import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from .doctor_verification import credential_for, is_verified, require_verified_doctor

router = APIRouter(prefix="/access-requests", tags=["access"])


def _notify_doctor(db: Session, grant: models.AccessGrant, patient: models.User, message: str) -> None:
    """Tell the doctor what the patient did with their access (the doctor's
    Notifications page; notifications are per user, whatever the role)."""
    db.add(models.Notification(patient_id=grant.provider_id, message=f"{patient.full_name} {message}"))


def _to_out(db: Session, grant: models.AccessGrant) -> schemas.AccessGrantOut:
    patient = db.query(models.User).filter(models.User.id == grant.patient_id).first()
    provider = db.query(models.User).filter(models.User.id == grant.provider_id).first()
    provider_profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == grant.provider_id).first()
    
    return schemas.AccessGrantOut(
        id=grant.id,
        patient_id=grant.patient_id,
        provider_id=grant.provider_id,
        status=grant.status,
        scope=json.loads(grant.scope),
        requested_at=grant.requested_at,
        responded_at=grant.responded_at,
        expires_at=grant.expires_at,
        patient_name=patient.full_name if patient else None,
        patient_email=patient.email if patient else None,
        provider_name=provider.full_name if provider else None,
        provider_email=provider.email if provider else None,
        provider_specialty=provider_profile.specialty if provider_profile else None,
        provider_hospital=provider_profile.hospital_name if provider_profile else None,
        provider_verified=is_verified(db, grant.provider_id),
    )


@router.post("", response_model=schemas.AccessGrantOut, status_code=201)
def request_access(
    payload: schemas.AccessRequestIn,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    require_verified_doctor(db, provider)
    patient = db.query(models.User).filter(
        models.User.id == payload.patient_id, models.User.role == models.UserRole.patient
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    grant = models.AccessGrant(
        patient_id=payload.patient_id,
        provider_id=provider.id,
        status=models.AccessStatus.pending,
        scope="[]",
    )
    db.add(grant)
    db.add(models.AuditLog(
        patient_id=payload.patient_id, actor_id=provider.id,
        action="access_requested", target_type="access_grant",
    ))
    db.commit()
    db.refresh(grant)
    return _to_out(db, grant)


@router.get("/pending", response_model=list[schemas.AccessGrantOut])
def list_pending_for_patient(
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    grants = (
        db.query(models.AccessGrant)
        .filter(
            models.AccessGrant.patient_id == patient.id,
            models.AccessGrant.status == models.AccessStatus.pending,
        )
        .all()
    )
    return [_to_out(db, g) for g in grants]


@router.get("/for-me", response_model=list[schemas.AccessGrantOut])
def list_all_for_patient(
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    """All of a patient's access grants regardless of status -- lets the
    patient dashboard show approved providers (so they can be revoked) as
    well as pending/denied/revoked history, not just the pending queue."""
    grants = (
        db.query(models.AccessGrant)
        .filter(models.AccessGrant.patient_id == patient.id)
        .order_by(models.AccessGrant.requested_at.desc())
        .all()
    )
    return [_to_out(db, g) for g in grants]


@router.get("/mine", response_model=list[schemas.AccessGrantOut])
def list_mine_for_provider(
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    """All access grants (any status) this provider has requested -- lets the
    provider dashboard show which patients they can currently view/add
    records for, and which requests are still pending or were denied."""
    grants = (
        db.query(models.AccessGrant)
        .filter(models.AccessGrant.provider_id == provider.id)
        .order_by(models.AccessGrant.requested_at.desc())
        .all()
    )
    return [_to_out(db, g) for g in grants]


@router.post("/{grant_id}/respond", response_model=schemas.AccessGrantOut)
def respond_to_request(
    grant_id: str,
    payload: schemas.AccessRespondIn,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    grant = db.query(models.AccessGrant).filter(models.AccessGrant.id == grant_id).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Access request not found.")
    if grant.patient_id != patient.id:
        raise HTTPException(status_code=403, detail="Not your access request.")

    grant.status = models.AccessStatus.approved if payload.approve else models.AccessStatus.denied
    grant.scope = json.dumps(payload.scope)
    grant.responded_at = datetime.utcnow()
    if payload.approve:
        grant.expires_at = datetime.utcnow() + timedelta(days=payload.expiry_days)

    db.add(models.AuditLog(
        patient_id=patient.id, actor_id=patient.id,
        action=f"access_{grant.status.value}", target_type="access_grant", target_id=grant.id,
    ))
    if payload.approve:
        shared = ", ".join(payload.scope).replace("_", " ") or "nothing yet"
        _notify_doctor(db, grant, patient,
                       f"approved your access request. You can see their {shared} until "
                       f"{grant.expires_at.strftime('%d %b %Y')}.")
    else:
        _notify_doctor(db, grant, patient, "declined your access request.")
    db.commit()
    db.refresh(grant)
    return _to_out(db, grant)

from ..llm import recommend_sharing_scope

@router.get("/{grant_id}/recommendation")
def get_ai_recommendation(
    grant_id: str,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    grant = db.query(models.AccessGrant).filter(models.AccessGrant.id == grant_id).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Access request not found.")
    if grant.patient_id != patient.id:
        raise HTTPException(status_code=403, detail="Not your access request.")
        
    provider_profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == grant.provider_id).first()
    specialty = provider_profile.specialty if provider_profile and provider_profile.specialty else "General Practitioner"
    
    # Everything the doctor submitted for verification, so a wrong Specialty
    # field (e.g. their name) doesn't spoil the recommendation.
    cred = credential_for(db, grant.provider_id)
    try:
        education = json.loads(cred.education) if cred and cred.education else []
    except ValueError:
        education = []

    return recommend_sharing_scope(
        specialty,
        qualification=cred.qualification if cred else "",
        hospital=provider_profile.hospital_name if provider_profile else "",
        education=education if isinstance(education, list) else [],
    )

@router.post("/{grant_id}/revoke", response_model=schemas.AccessGrantOut)
def revoke_access(
    grant_id: str,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    grant = db.query(models.AccessGrant).filter(models.AccessGrant.id == grant_id).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Access grant not found.")
    if grant.patient_id != patient.id:
        raise HTTPException(status_code=403, detail="Not your access grant.")

    grant.status = models.AccessStatus.revoked
    db.add(models.AuditLog(
        patient_id=patient.id, actor_id=patient.id,
        action="access_revoked", target_type="access_grant", target_id=grant.id,
    ))
    _notify_doctor(db, grant, patient, "revoked your access to their records.")
    db.commit()
    db.refresh(grant)
    return _to_out(db, grant)
