"""
Consultation note <-> prescription links (see app/linking.py for matching).

GET  /links/patient/{patient_id}                  current links for a patient's timeline
GET  /links/consultation/{id}/candidates          every prescription, scored, for manual choice
POST /links/consultation/{id}/override            manual link/unlink with a documented reason
POST /links/{link_id}/accept                      patient confirms a proposed link (final)
POST /links/{link_id}/reject                      patient rejects a proposed link

A "linked" row is a proposal until the patient accepts it. "confirmed" links
can't be changed or removed by anyone.
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, auth, linking
from ..access_control import assert_can_view_patient
from ..database import get_db

router = APIRouter(prefix="/links", tags=["links"])


class OverrideIn(BaseModel):
    document_id: Optional[str] = None  # None = "no linked prescription"
    reason: str


class RejectIn(BaseModel):
    reason: Optional[str] = None


def _can_see_prescriptions(grant) -> bool:
    """Doctors only see prescription details if the patient shared medications."""
    if grant is None:  # the patient themself
        return True
    scope = json.loads(grant.scope or "[]")
    return "full_history" in scope or "medications" in scope


def _note_content(db: Session, note: models.MedicalRecord, author) -> dict:
    """What the doctor wrote in the consultation, from their own account."""
    d = json.loads(note.details) if note.details else {}
    d = d if isinstance(d, dict) else {"text": str(d)}
    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == author.id).first() if author else None
    return {
        "text": d.get("text") or d.get("notes") or "",
        "follow_up": d.get("follow_up") or "",
        "author_specialty": profile.specialty if profile else None,
        "author_hospital": profile.hospital_name if profile else None,
        "added_at": note.created_at,
    }


def _link_out(db: Session, link: models.RecordLink, show_docs: bool, viewer: Optional[models.User] = None,
              grant=None) -> dict:
    note = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == link.consultation_id).first()
    author = db.query(models.User).filter(models.User.id == note.created_by).first() if note else None
    # The note's content goes to the patient, its author, and doctors with full
    # history -- the same people who see consultation notes on the timeline.
    show_note = (viewer is None or viewer.role == models.UserRole.patient
                 or (note is not None and note.created_by == viewer.id)
                 or (grant is not None and "full_history" in json.loads(grant.scope or "[]")))
    by = db.query(models.User).filter(models.User.id == link.created_by).first() if link.created_by else None

    def doc(doc_id):
        d = db.query(models.Document).filter(models.Document.id == doc_id).first()
        return linking.document_summary(db, d) if d else None

    return {
        "id": link.id,
        "ref": "L-" + link.id[:6].upper(),
        "status": link.status,
        "method": link.method,
        "score": link.score,
        "match_reason": link.match_reason,
        "process": link.process,
        "override_reason": link.override_reason,
        "overridden_by": by.full_name if by else None,
        "created_at": link.created_at,
        "updated_at": link.updated_at,
        "awaiting_patient": link.status == "linked",
        "confirmed_at": link.updated_at if link.status == "confirmed" else None,
        "consultation": {
            "id": note.id, "title": note.title, "date": note.record_date.isoformat(),
            "author_id": author.id if author else None, "author_name": author.full_name if author else None,
            **(_note_content(db, note, author) if show_note else {}),
        } if note else None,
        "hidden": not show_docs,
        "document": doc(link.document_id) if show_docs and link.document_id else None,
        "candidates": [doc(i) for i in json.loads(link.candidate_document_ids or "[]")] if show_docs else [],
    }


def _load_note(db: Session, consultation_id: str) -> models.MedicalRecord:
    note = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == consultation_id).first()
    if not note or note.record_type != models.RecordType.consultation or not note.created_by:
        raise HTTPException(status_code=404, detail="Consultation note not found.")
    return note


@router.get("/patient/{patient_id}")
def list_links(
    patient_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    grant = assert_can_view_patient(db, user, patient_id)
    linking.backfill_missing(db, patient_id)
    db.commit()
    links = db.query(models.RecordLink).filter(models.RecordLink.patient_id == patient_id).all()
    show = _can_see_prescriptions(grant)
    return [_link_out(db, link, show, user, grant) for link in links]


@router.get("/consultation/{consultation_id}/candidates")
def list_candidates(
    consultation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    note = _load_note(db, consultation_id)
    grant = assert_can_view_patient(db, user, note.patient_id)
    if not _can_see_prescriptions(grant):
        raise HTTPException(status_code=403, detail="The patient hasn't shared their prescriptions with you.")
    author = db.query(models.User).filter(models.User.id == note.created_by).first()
    return [
        {
            **linking.document_summary(db, c["document"]),
            "score": c["score"], "name_score": c["name_score"], "days_apart": c["days_apart"],
            "eligible": c["eligible"],
            "reason": linking._reason(c, author.full_name) if c["eligible"] else
                      (f"prescribed by {c['doctor']}" if c["doctor"] else "prescribing doctor not found on it"),
        }
        for c in linking.score_candidates(db, note, author)
    ]


@router.post("/consultation/{consultation_id}/override")
def override_link(
    consultation_id: str,
    payload: OverrideIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    note = _load_note(db, consultation_id)
    grant = assert_can_view_patient(db, user, note.patient_id)
    # Authorized: the patient, or the doctor who wrote the note (with current access).
    if user.role == models.UserRole.provider and note.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the note's author or the patient can change this link.")
    if user.role == models.UserRole.provider and not _can_see_prescriptions(grant):
        raise HTTPException(status_code=403, detail="The patient hasn't shared their prescriptions with you.")
    existing = db.query(models.RecordLink).filter(models.RecordLink.consultation_id == note.id).first()
    if existing and existing.status == "confirmed":
        raise HTTPException(status_code=409, detail="The patient has confirmed this link, so it can't be changed.")
    reason = (payload.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=400, detail="Please give a reason for the change (at least 5 characters).")

    if payload.document_id:
        doc = db.query(models.Document).filter(models.Document.id == payload.document_id).first()
        if (not doc or doc.patient_id != note.patient_id or doc.uploaded_by != note.patient_id
                or doc.document_type != "prescription"):
            raise HTTPException(status_code=400, detail="That isn't one of this patient's uploaded prescriptions.")

    link = db.query(models.RecordLink).filter(models.RecordLink.consultation_id == note.id).first()
    now = datetime.utcnow()
    if not link:
        link = models.RecordLink(patient_id=note.patient_id, consultation_id=note.id, created_at=now)
        db.add(link)
    link.document_id = payload.document_id
    link.status = "linked" if payload.document_id else "unmatched"
    link.method = "manual"
    link.score = None
    link.candidate_document_ids = "[]"
    link.match_reason = "Linked manually." if payload.document_id else "Marked as having no related prescription."
    link.process = "manual override"
    link.created_by = user.id
    link.override_reason = reason
    link.updated_at = now
    db.flush()
    db.add(models.AuditLog(patient_id=note.patient_id, actor_id=user.id, action="record_link_overridden",
                           target_type="record_link", target_id=link.id))
    db.commit()
    db.refresh(link)
    return _link_out(db, link, True)


def _patient_link(db: Session, link_id: str, user: models.User) -> models.RecordLink:
    if user.role != models.UserRole.patient:
        raise HTTPException(status_code=403, detail="Only the patient can confirm or reject a link.")
    link = db.query(models.RecordLink).filter(models.RecordLink.id == link_id).first()
    if not link or link.patient_id != user.id:
        raise HTTPException(status_code=404, detail="Link not found.")
    if link.status == "confirmed":
        raise HTTPException(status_code=409, detail="You've already confirmed this link; it can't be changed.")
    return link


@router.post("/{link_id}/accept")
def accept_link(
    link_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Patient confirms the proposed prescription. Final: the link is locked."""
    link = _patient_link(db, link_id, user)
    if link.status != "linked" or not link.document_id:
        raise HTTPException(status_code=400, detail="There's no proposed prescription to confirm for this note.")
    link.status = "confirmed"
    link.updated_at = datetime.utcnow()
    db.add(models.AuditLog(patient_id=user.id, actor_id=user.id, action="record_link_confirmed",
                           target_type="record_link", target_id=link.id))
    db.commit()
    db.refresh(link)
    return _link_out(db, link, True)


@router.post("/{link_id}/reject")
def reject_link(
    link_id: str,
    payload: Optional[RejectIn] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Patient says the proposed prescription is wrong. The auto-linker won't
    propose it again; the doctor can still propose another one manually."""
    link = _patient_link(db, link_id, user)
    link.document_id = None
    link.status = "unmatched"
    link.method = "manual"
    link.candidate_document_ids = "[]"
    link.score = None
    link.match_reason = "The patient rejected the proposed prescription."
    link.override_reason = ((payload.reason if payload else None) or "").strip() or "Rejected by the patient"
    link.created_by = user.id
    link.process = "rejected by patient"
    link.updated_at = datetime.utcnow()
    db.add(models.AuditLog(patient_id=user.id, actor_id=user.id, action="record_link_rejected",
                           target_type="record_link", target_id=link.id))
    db.commit()
    db.refresh(link)
    return _link_out(db, link, True)
