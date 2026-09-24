import json
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..serializers import record_to_out
from ..intelligence import detect_conflicts
from ..access_control import assert_can_view_patient

router = APIRouter(prefix="/timeline", tags=["timeline"])


_RECORD_TYPE_WORDS = {"medication", "medications", "diagnosis", "diagnoses", "consultation",
                      "lab_result", "lab result", "lab", "allergy", "hospitalization", "record", "source"}


def _clean_citations(text: str, valid_ids) -> str:
    """
    Repair the citation links Gemini writes before the frontend renders them
    as Markdown. Seen in practice:
      [medication](#abc]        -> wrong closing bracket
      [medication]\n(#abc)       -> link split across a line break
      [medication](abc)         -> missing '#'
    Links to ids that aren't in the patient's (scope-filtered) records are
    dropped to plain text, and generic labels ("medication", "lab_result")
    become "source" so the prose reads naturally.
    """
    text = re.sub(r"\]\s*\n\s*\(", "](", text)                              # join split links
    text = re.sub(r"\(#?([0-9a-fA-F]{32})\s*\]", r"(#\1)", text)            # (#id]  -> (#id)
    text = re.sub(r"\]\(([0-9a-fA-F]{32})\)", r"](#\1)", text)               # (id)   -> (#id)

    def fix(m):
        label, rid = m.group(1).strip(), m.group(2)
        if rid not in valid_ids:
            return "" if label.lower() in _RECORD_TYPE_WORDS else label
        if label.lower().replace("_", " ") in _RECORD_TYPE_WORDS:
            label = "source"
        return f"[{label}](#{rid})"

    text = re.sub(r"\[([^\]\n]{1,80})\]\(#([0-9a-zA-Z_-]+)\)", fix, text)
    # tidy spaces left before punctuation by dropped links
    return re.sub(r"[ \t]+([.,;:])", r"\1", text)


def _fallback_summary(records) -> str:
    """Plain factual digest used when Gemini is unavailable. Same citation
    link format as the AI summary ([label](#record-id)) so the panel's
    click-to-highlight still works. Makes no clinical inferences."""
    def cite(rs):
        return ", ".join(f"[{r.title}](#{r.id})" for r in rs)

    by_type = {}
    for r in records:
        by_type.setdefault(r.record_type.value, []).append(r)

    parts = ["_AI summary is unavailable right now; showing key facts from the shared records._"]
    labels = [
        ("allergy", "Allergies"), ("diagnosis", "Diagnoses"), ("medication", "Medications"),
        ("lab_result", "Lab results"), ("hospitalization", "Hospital stays"),
        ("consultation", "Consultations"),
    ]
    for key, label in labels:
        rs = by_type.get(key)
        if rs:
            recent = sorted(rs, key=lambda r: r.record_date, reverse=True)[:5]
            more = f" (+{len(rs) - 5} more)" if len(rs) > 5 else ""
            parts.append(f"**{label}:** {cite(recent)}{more}")
    latest = max(records, key=lambda r: r.record_date)
    parts.append(f"**Most recent entry:** [{latest.title}](#{latest.id}) on {latest.record_date.isoformat()}")
    return "\n\n".join(parts)


@router.get("/{patient_id}", response_model=schemas.TimelineOut)
def get_timeline(
    patient_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    grant = assert_can_view_patient(db, user, patient_id)

    # Timeline shows everything EXCEPT still-unverified AI extractions --
    # those live in /records/unverified until a human confirms them (FR-4.1).
    query = (
        db.query(models.MedicalRecord)
        .filter(
            models.MedicalRecord.patient_id == patient_id,
            ~(
                (models.MedicalRecord.source_type == models.SourceType.ai_extracted)
                & (models.MedicalRecord.verification_status == models.VerificationStatus.unverified)
            ),
        )
    )

    if grant and grant.scope:
        try:
            scope = json.loads(grant.scope)
            if not scope:
                # Empty scope means the doctor was approved but granted NO scopes. They see nothing.
                query = query.filter(models.MedicalRecord.id == "force_empty_result")
            elif "full_history" not in scope:
                # Map frontend strings to backend RecordType enums
                scope_mapping = {
                    "medications": models.RecordType.medication,
                    "labs": models.RecordType.lab_result,
                    "allergies": models.RecordType.allergy,
                    "diagnoses": models.RecordType.diagnosis
                }
                allowed_types = [scope_mapping[s] for s in scope if s in scope_mapping]
                if not allowed_types:
                    query = query.filter(models.MedicalRecord.id == "force_empty_result")
                else:
                    query = query.filter(models.MedicalRecord.record_type.in_(allowed_types))
        except json.JSONDecodeError:
            pass

    records = query.order_by(models.MedicalRecord.record_date.asc()).all()

    raw = [
        {
            "id": r.id,
            "record_type": r.record_type,
            "details": r.details,
            "record_date": r.record_date,
        }
        for r in records
    ]
    flags = detect_conflicts(raw)

    return schemas.TimelineOut(
        records=[record_to_out(r) for r in records],
        flags=[schemas.TimelineFlag(**f) for f in flags],
    )


@router.get("/{patient_id}/summary")
def get_timeline_summary(
    patient_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    grant = assert_can_view_patient(db, user, patient_id)

    query = (
        db.query(models.MedicalRecord)
        .filter(
            models.MedicalRecord.patient_id == patient_id,
            ~(
                (models.MedicalRecord.source_type == models.SourceType.ai_extracted)
                & (models.MedicalRecord.verification_status == models.VerificationStatus.unverified)
            ),
        )
    )

    if grant and grant.scope:
        try:
            scope = json.loads(grant.scope)
            if not scope:
                query = query.filter(models.MedicalRecord.id == "force_empty_result")
            elif "full_history" not in scope:
                scope_mapping = {
                    "medications": models.RecordType.medication,
                    "labs": models.RecordType.lab_result,
                    "allergies": models.RecordType.allergy,
                    "diagnoses": models.RecordType.diagnosis
                }
                allowed_types = [scope_mapping[s] for s in scope if s in scope_mapping]
                if not allowed_types:
                    query = query.filter(models.MedicalRecord.id == "force_empty_result")
                else:
                    query = query.filter(models.MedicalRecord.record_type.in_(allowed_types))
        except json.JSONDecodeError:
            pass

    records = query.order_by(models.MedicalRecord.record_date.asc()).all()

    if not records:
        return {"summary": "No records available for summary."}

    clean_records = []
    for r in records:
        clean_records.append({
            "id": r.id,
            "type": r.record_type,
            "date": r.record_date.isoformat() if hasattr(r.record_date, "isoformat") else r.record_date,
            "details": r.details
        })

    prompt = f"""
    You are a clinical intelligence AI. Write a brief, 1-paragraph clinical summary for a busy doctor based on the following patient records.
    
    CRITICAL REQUIREMENT:
    You MUST cite your sources for any clinical claim you make by appending a Markdown link to the relevant record's ID.
    Format every link EXACTLY as [source](#<id>) on a single line, where <id> is the exact "id" value of the record.
    For example: "The patient was diagnosed with hypertension [source](#3f2a9c...)."
    Only cite ids that appear in the JSON below.
    
    Here is the patient's record timeline (JSON):
    {json.dumps(clean_records)}
    
    Output ONLY the markdown summary text. Do not include any JSON wrapping.
    """
    
    from ..llm import generate_content

    try:
        response = generate_content(prompt, purpose="Summary")
        return {"summary": _clean_citations(response.text or "", {r.id for r in records})}
    except Exception as e:
        print(f"Summary: all Gemini models unavailable ({str(e).split('.', 1)[0][:60]}), using factual fallback")
        return {"summary": _fallback_summary(records)}
