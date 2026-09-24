from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=list[schemas.AuditLogOut])
def my_audit_log(
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    rows = (
        db.query(models.AuditLog, models.User)
        .outerjoin(models.User, models.User.id == models.AuditLog.actor_id)
        .filter(models.AuditLog.patient_id == patient.id)
        .order_by(models.AuditLog.timestamp.desc())
        .all()
    )
    return [
        schemas.AuditLogOut(
            id=log.id, actor_id=log.actor_id, action=log.action, target_type=log.target_type,
            target_id=log.target_id, timestamp=log.timestamp,
            actor_name=actor.full_name if actor else None,
            actor_role=actor.role.value if actor else None,
        )
        for log, actor in rows
    ]
