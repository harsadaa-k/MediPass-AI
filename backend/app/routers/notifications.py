from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[schemas.NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """List all notifications for the current user, newest first."""
    return (
        db.query(models.Notification)
        .filter(models.Notification.patient_id == user.id)
        .order_by(models.Notification.created_at.desc())
        .limit(50)
        .all()
    )


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Mark every unread notification of the current user as read."""
    count = (
        db.query(models.Notification)
        .filter(models.Notification.patient_id == user.id, models.Notification.is_read.is_(False))
        .update({models.Notification.is_read: True})
    )
    db.commit()
    return {"marked": count}


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Mark a notification as read."""
    notif = (
        db.query(models.Notification)
        .filter(
            models.Notification.id == notification_id,
            models.Notification.patient_id == user.id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")
    notif.is_read = True
    db.commit()
    return {"message": "Notification marked as read."}
