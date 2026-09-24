"""
Auto-linking a doctor's consultation notes to the patient-uploaded
prescription written by the same doctor.

Triggers (all call link_consultation):
  * a doctor adds a consultation note          -> "consultation added"
  * the patient uploads a prescription         -> re-run for that patient's
    unmatched / ambiguous auto links            ("prescription uploaded")
  * the timeline links are listed and an older
    consultation has no link row yet           -> "backfill"

Matching:
  1. Candidates = the patient's own uploaded prescriptions whose prescribing
     doctor (details.doctor_name on its records, else "Dr. X" in the OCR
     text) matches the note's author: name_score >= NAME_THRESHOLD.
  2. Each candidate is scored
        0.45 * name_score + 0.25 * date_score + 0.15 * context_score
        + 0.15 * hospital_score
     date_score     = 1 / (1 + days_apart / 14)   (x0.9 if the prescription is
                      dated after the note)
     context_score  = share of the prescription's medicines / diagnoses that
                      the note mentions
     hospital_score = similarity of the hospital/clinic on the prescription to
                      the doctor's profile hospital (0 if either is unknown)
  3. 0 candidates -> unmatched; 1 -> linked; several -> linked to the best
     only if it beats the runner-up by AMBIGUITY_MARGIN, otherwise ambiguous
     (top 3 kept as candidates for a person to choose).

Patient confirmation: a "linked" row is only a proposal. The patient accepts
it (-> "confirmed") or rejects it. Confirmed links are final: the
auto-linker, doctors and the patient can no longer change or remove them.
Manual overrides (patient, or the note's author) are stored with a reason and
are never overwritten by the auto-linker.
"""
import difflib
import json
import re
from collections import Counter
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from . import models

PROCESS = "auto-linker v1"
NAME_THRESHOLD = 0.75
AMBIGUITY_MARGIN = 0.1
MAX_CANDIDATES = 3

_TITLES = {"dr", "doctor", "prof", "professor", "mr", "mrs", "ms", "mbbs", "md", "ms", "dnb", "frcs", "mrcp"}
_DR_IN_TEXT = re.compile(r"\b(?:Dr|Doctor)\.?\s+((?:[A-Z]\.\s*)*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")


# ---------------------------------------------------------------- names

def _name_tokens(name: str) -> List[str]:
    tokens = re.findall(r"[a-z]+", (name or "").lower())
    return [t for t in tokens if t not in _TITLES]


def name_similarity(a: str, b: str) -> float:
    """0..1. Handles titles ("Dr."), initials ("R. Mehta" ~ "Rajesh Mehta")
    and small spelling differences ("Dubey" ~ "Dube")."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    seq = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    surname_close = difflib.SequenceMatcher(None, ta[-1], tb[-1]).ratio() >= 0.85
    initials_ok = ta[0][0] == tb[0][0]
    subset = set(ta) <= set(tb) or set(tb) <= set(ta)
    score = seq
    if surname_close and initials_ok:
        score = max(score, 0.9)
    elif surname_close and (len(ta) == 1 or len(tb) == 1):
        score = max(score, 0.8)  # "Dr. Mehta" vs "Rajesh Mehta"
    if subset:
        score = max(score, 0.85)
    return round(min(score, 1.0), 3)


# ---------------------------------------------------------------- prescriptions

def prescription_info(db: Session, doc: models.Document) -> Dict:
    """Doctor, date and contents of an uploaded prescription."""
    records = db.query(models.MedicalRecord).filter(models.MedicalRecord.source_document_id == doc.id).all()
    names, dates, meds, terms = Counter(), Counter(), set(), set()
    for r in records:
        d = json.loads(r.details) if r.details else {}
        if d.get("doctor_name"):
            names[d["doctor_name"].strip()] += 1
        if not d.get("is_fallback_date"):
            dates[r.record_date] += 1
        if r.record_type == models.RecordType.medication:
            med = (d.get("medicine") or r.title or "").lower()
            meds.update(w for w in re.findall(r"[a-z]{4,}", med) if w not in {"tab", "tablet", "caps", "syrup"})
        if r.record_type == models.RecordType.diagnosis:
            terms.update(w for w in re.findall(r"[a-z]{5,}", (r.title or "").lower()))
    doctor = names.most_common(1)[0][0] if names else ""
    if not doctor and doc.raw_text:
        m = _DR_IN_TEXT.search(doc.raw_text)
        doctor = f"Dr. {m.group(1)}" if m else ""
    hospitals = Counter(
        (json.loads(r.details) if r.details else {}).get("hospital_name", "").strip() for r in records
    )
    hospitals.pop("", None)
    hospital = hospitals.most_common(1)[0][0] if hospitals else ""
    doc_date = dates.most_common(1)[0][0] if dates else (records[0].record_date if records else None)
    return {"doctor": doctor, "hospital": hospital, "date": doc_date, "medicines": meds, "terms": terms}


_ORG_STOPWORDS = {"hospital", "hospitals", "clinic", "clinics", "the", "and", "of", "centre", "center",
                  "medical", "nursing", "home", "pvt", "ltd", "multispeciality", "multispecialty"}


def hospital_similarity(a: str, b: str) -> float:
    """'City Clinic' ~ 'City Clinic, Bengaluru' ~ 'CITY CLINIC'. 0 if either is unknown."""
    ta = [t for t in re.findall(r"[a-z]+", (a or "").lower()) if t not in _ORG_STOPWORDS]
    tb = [t for t in re.findall(r"[a-z]+", (b or "").lower()) if t not in _ORG_STOPWORDS]
    if not ta or not tb:
        return 0.0
    if set(ta) <= set(tb) or set(tb) <= set(ta):
        return 1.0
    return round(difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio(), 3)


def _patient_prescriptions(db: Session, patient_id: str) -> List[models.Document]:
    return (
        db.query(models.Document)
        .filter(
            models.Document.patient_id == patient_id,
            models.Document.uploaded_by == patient_id,
            models.Document.document_type == "prescription",
        )
        .order_by(models.Document.upload_date.asc())
        .all()
    )


def score_candidates(db: Session, consultation: models.MedicalRecord, author: models.User) -> List[Dict]:
    """All of the patient's prescriptions, scored against this note (best first).
    'eligible' = the prescribing doctor matches the note's author."""
    details = json.loads(consultation.details) if consultation.details else {}
    note_text = " ".join(str(v) for v in [consultation.title, *details.values()]).lower()
    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == author.id).first()
    author_hospital = (profile.hospital_name or "") if profile else ""
    out = []
    for doc in _patient_prescriptions(db, consultation.patient_id):
        info = prescription_info(db, doc)
        name = name_similarity(author.full_name, info["doctor"]) if info["doctor"] else 0.0
        days = abs((consultation.record_date - info["date"]).days) if info["date"] else None
        date_score = 0.0 if days is None else 1 / (1 + days / 14)
        if info["date"] and info["date"] > consultation.record_date:
            date_score *= 0.9
        vocab = info["medicines"] | info["terms"]
        context = (sum(1 for w in vocab if w in note_text) / len(vocab)) if vocab else 0.0
        hospital = hospital_similarity(info["hospital"], author_hospital)
        total = 0.45 * name + 0.25 * date_score + 0.15 * min(context * 2, 1.0) + 0.15 * hospital
        out.append({
            "document": doc, "doctor": info["doctor"], "hospital": info["hospital"], "date": info["date"],
            "name_score": name, "hospital_score": hospital, "days_apart": days,
            "context_score": round(context, 3),
            "score": round(total, 3), "eligible": name >= NAME_THRESHOLD,
        })
    out.sort(key=lambda c: (c["eligible"], c["score"]), reverse=True)
    return out


def _reason(c: Dict, author_name: str) -> str:
    bits = [f"prescribed by {c['doctor']} (matches {author_name})"]
    if c.get("hospital_score", 0) >= 0.8:
        bits.append(f"same hospital ({c['hospital']})")
    if c["days_apart"] is not None:
        bits.append("same day" if c["days_apart"] == 0 else f"{c['days_apart']} days apart")
    if c["context_score"]:
        bits.append("mentions the same medicines")
    return ", ".join(bits)


# ---------------------------------------------------------------- linking

def link_consultation(db: Session, consultation: models.MedicalRecord, trigger: str) -> Optional[models.RecordLink]:
    """Create/refresh the auto link for one consultation note. Leaves manual
    links alone. Writes an audit row only when the link state changes."""
    if consultation.record_type != models.RecordType.consultation or not consultation.created_by:
        return None
    link = db.query(models.RecordLink).filter(models.RecordLink.consultation_id == consultation.id).first()
    if link and (link.method == "manual" or link.status == "confirmed"):
        return link
    author = db.query(models.User).filter(models.User.id == consultation.created_by).first()
    if not author:
        return None

    eligible = [c for c in score_candidates(db, consultation, author) if c["eligible"]]
    doc_id, status, score, reason, candidates = None, "unmatched", None, "", []
    if not eligible:
        reason = (f"No prescription from {author.full_name} among the patient's uploads yet — "
                  f"it will link automatically when one is uploaded.")
    elif len(eligible) == 1 or eligible[0]["score"] - eligible[1]["score"] >= AMBIGUITY_MARGIN - 1e-9:
        best = eligible[0]
        doc_id, status, score = best["document"].id, "linked", best["score"]
        reason = _reason(best, author.full_name)
    else:
        status = "ambiguous"
        candidates = [c["document"].id for c in eligible[:MAX_CANDIDATES]]
        score = eligible[0]["score"]
        reason = (f"{len(eligible)} prescriptions from {author.full_name} match about equally well — "
                  f"please choose the right one.")

    changed = (not link or link.status != status or link.document_id != doc_id
               or json.loads(link.candidate_document_ids or "[]") != candidates)
    now = datetime.utcnow()
    if not link:
        link = models.RecordLink(patient_id=consultation.patient_id, consultation_id=consultation.id,
                                 created_at=now)
        db.add(link)
    link.document_id, link.status, link.score, link.match_reason = doc_id, status, score, reason
    link.candidate_document_ids = json.dumps(candidates)
    link.method, link.process, link.updated_at = "auto", f"{PROCESS} ({trigger})", now
    db.flush()

    if changed and status in ("linked", "ambiguous"):
        db.add(models.AuditLog(
            patient_id=consultation.patient_id, actor_id=author.id,
            action="record_linked" if status == "linked" else "record_link_needs_review",
            target_type="record_link", target_id=link.id,
        ))
    return link


def relink_patient(db: Session, patient_id: str, trigger: str) -> None:
    """Re-run auto matching for a patient's notes that aren't settled yet
    (e.g. the prescription was uploaded after the consultation note)."""
    notes = (
        db.query(models.MedicalRecord)
        .filter(
            models.MedicalRecord.patient_id == patient_id,
            models.MedicalRecord.record_type == models.RecordType.consultation,
            models.MedicalRecord.source_type == models.SourceType.doctor_generated,
        )
        .all()
    )
    for note in notes:
        link = db.query(models.RecordLink).filter(models.RecordLink.consultation_id == note.id).first()
        if link is None or (link.method == "auto" and link.status in ("unmatched", "ambiguous")):
            link_consultation(db, note, trigger)


def backfill_missing(db: Session, patient_id: str) -> None:
    """Older consultation notes written before auto-linking existed."""
    missing = (
        db.query(models.MedicalRecord)
        .outerjoin(models.RecordLink, models.RecordLink.consultation_id == models.MedicalRecord.id)
        .filter(
            models.MedicalRecord.patient_id == patient_id,
            models.MedicalRecord.record_type == models.RecordType.consultation,
            models.MedicalRecord.source_type == models.SourceType.doctor_generated,
            models.RecordLink.id.is_(None),
        )
        .all()
    )
    for note in missing:
        link_consultation(db, note, "backfill")


def document_summary(db: Session, doc: models.Document) -> Dict:
    info = prescription_info(db, doc)
    # What the prescription says, so the link panel can show it in place:
    # each medicine with dose / timing / course, and any diagnoses on it.
    from .durations import medication_course
    items, diagnoses = [], []
    for r in (db.query(models.MedicalRecord).filter(models.MedicalRecord.source_document_id == doc.id)
              .order_by(models.MedicalRecord.created_at)):
        d = json.loads(r.details) if r.details else {}
        d = d if isinstance(d, dict) else {}
        if r.record_type == models.RecordType.medication:
            course = medication_course(d, r.record_date)
            items.append({
                "name": d.get("medicine") or r.title, "dose": d.get("dose") or "",
                "timing": d.get("timing") or d.get("frequency") or "",
                "instructions": d.get("intake_status") or "",
                "course": (course or {}).get("duration") or d.get("duration") or "",
            })
        elif r.record_type == models.RecordType.diagnosis:
            diagnoses.append(r.title)
    return {
        "id": doc.id, "file_name": doc.file_name, "doctor": info["doctor"] or None,
        "hospital": info["hospital"] or None,
        "date": info["date"].isoformat() if isinstance(info["date"], date) else None,
        "medicines": sorted(info["medicines"])[:8],
        "items": items[:20],
        "diagnoses": diagnoses[:10],
    }
