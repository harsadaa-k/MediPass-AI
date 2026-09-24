from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from . import models


def assert_can_view_patient(db: Session, user: models.User, patient_id: str) -> Optional[models.AccessGrant]:
    """
    A patient can always view their own data. A provider may only view a
    patient's data if they hold an *approved* access grant for them
    (FR-5.3). Enforced here so every route that reads patient data goes
    through the same check.
    """
    if user.role == models.UserRole.patient:
        if user.id != patient_id:
            raise HTTPException(status_code=403, detail="Not your data.")
        return None

    # provider
    grant = (
        db.query(models.AccessGrant)
        .filter(
            models.AccessGrant.patient_id == patient_id,
            models.AccessGrant.provider_id == user.id,
            models.AccessGrant.status == models.AccessStatus.approved,
        )
        .first()
    )
    if not grant:
        raise HTTPException(
            status_code=403,
            detail="No approved access grant for this patient.",
        )

    if grant.expires_at and datetime.utcnow() > grant.expires_at:
        grant.status = models.AccessStatus.revoked
        db.add(models.AuditLog(
            patient_id=patient_id, actor_id=user.id,
            action="access_auto_revoked", target_type="access_grant", target_id=grant.id,
        ))
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Access grant has expired.",
        )

    return grant
