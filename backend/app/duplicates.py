"""
Duplicate detection.

Two layers:
  * files: the SHA-256 of an upload. Uploading the identical file again is
    caught before any AI call (routers/documents.py).
  * records: the same prescription photographed or cropped differently gives
    a different file but the same entries. A record is a likely duplicate of
    another when both are the same type, carry the same consultation date,
    come from different uploads, and
      - medications: medicine names are near-identical (>= 0.85 similarity,
        so OCR/AI spelling slips like "Zocalm"/"Zolcalm" still match) and
        the doses agree (or one has no dose);
      - everything else: the titles are near-identical and so is the text
        (both empty counts as the same).
    Duplicates are only flagged; the patient decides what to remove
    (Verify records), or the cleanup script find_duplicates.py lists them.
"""
import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from . import models
from .storage import read_upload

NAME_SIMILARITY = 0.85
_FORM_WORDS = r"(tab|tabs|tablet|tablets|cap|caps|capsule|capsules|syp|syrup|inj|injection|oint|ointment|gel|drops?)"
_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|µg|g|gm|ml|iu|units?|%)", re.I)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def document_hash(db: Session, doc: models.Document) -> Optional[str]:
    """The stored hash; older uploads get theirs computed once and saved."""
    if doc.content_sha256:
        return doc.content_sha256
    if not doc.file_path:
        return None
    try:
        doc.content_sha256 = sha256(read_upload(doc.file_path))
    except OSError:
        return None
    db.add(doc)
    return doc.content_sha256


def find_same_file(db: Session, patient_id: str, digest: str) -> Optional[models.Document]:
    """An earlier upload of the identical file that still has records."""
    docs = (db.query(models.Document)
            .filter(models.Document.patient_id == patient_id)
            .order_by(models.Document.upload_date.desc()).all())
    for doc in docs:
        if document_hash(db, doc) != digest:
            continue
        has_records = db.query(models.MedicalRecord.id).filter(
            models.MedicalRecord.source_document_id == doc.id).first()
        if has_records:
            return doc
    return None


# ---------------------------------------------------------------- records

def _details(record: models.MedicalRecord) -> dict:
    try:
        d = json.loads(record.details or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _medicine_name(record, details) -> str:
    text = (details.get("medicine") or record.title or "").lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(rf"\b{_FORM_WORDS}\b\.?", " ", text)
    words = re.findall(r"[a-z][a-z\-]{2,}", text)
    return words[0] if words else ""


def _dose(record, details) -> str:
    m = _DOSE.search(str(details.get("dose") or "")) or _DOSE.search(record.title or "")
    if not m:
        return ""
    unit = m.group(2).lower().replace("gm", "g")
    return f"{float(m.group(1)):g}{unit}"


def _title_key(record) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (record.title or "").lower()))


def _text_key(details: dict) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(details.get("text") or details.get("notes") or "").lower()))


def _similar(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or SequenceMatcher(None, a, b).ratio() >= NAME_SIMILARITY)


def is_duplicate(a: models.MedicalRecord, b: models.MedicalRecord) -> bool:
    if a.id == b.id or a.record_type != b.record_type or a.record_date != b.record_date:
        return False
    if a.source_document_id and a.source_document_id == b.source_document_id:
        return False  # two entries on one prescription aren't duplicates
    da, db_ = _details(a), _details(b)
    if a.record_type == models.RecordType.medication:
        dose_a, dose_b = _dose(a, da), _dose(b, db_)
        if dose_a and dose_b and dose_a != dose_b:
            return False
        return _similar(_medicine_name(a, da), _medicine_name(b, db_))
    if not _similar(_title_key(a), _title_key(b)):
        return False
    # generic titles ("Note from prescription") say nothing: the text must match too
    text_a, text_b = _text_key(da), _text_key(db_)
    return text_a == text_b or _similar(text_a, text_b)


def timeline_records(db: Session, patient_id: str) -> List[models.MedicalRecord]:
    """Records already on the patient's timeline (not waiting for review)."""
    return db.query(models.MedicalRecord).filter(
        models.MedicalRecord.patient_id == patient_id,
        models.MedicalRecord.verification_status != models.VerificationStatus.unverified,
    ).all()


def find_duplicate_of(record: models.MedicalRecord, pool: Iterable[models.MedicalRecord]) -> Optional[models.MedicalRecord]:
    for other in pool:
        if is_duplicate(record, other):
            return other
    return None
