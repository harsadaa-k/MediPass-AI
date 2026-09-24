import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session

from pydantic import BaseModel

from .. import models, schemas, auth, imaging, linking, duplicates
from ..database import get_db
from ..llm import extract_medical_records
from ..storage import save_upload, read_upload
from ..access_control import assert_can_view_patient

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf", "application/dicom"}
# "discharge_summary" was removed from uploads. Documents already stored with
# that type keep it (document_type is a plain string column) and still render.
ALLOWED_DOC_TYPES = {"prescription", "lab_report"}

# Fewer real words than this from OCR on an image uploaded as a lab report
# means it's a scan/X-ray, not a photographed text report.
_MIN_WORDS_FOR_TEXT_DOCUMENT = 8


def _study_date(meta) -> date:
    try:
        return datetime.strptime(meta.get("study_date", ""), "%Y%m%d").date()
    except ValueError:
        return date.today()


def _apply_dicom(records, meta, png_available: bool):
    """Merge DICOM metadata into the image record (adding one if the AI
    returned no imaging record), reconciling the body part."""
    dicom_part = imaging.body_part_from_dicom(meta)
    image_recs = [r for r in records if r["details"].get("body_part")]
    if not image_recs:
        rec = imaging.imaging_record("unknown", 0.0, "none")
        records.append(rec)
        image_recs = [rec]

    for rec in image_recs:
        d = rec["details"]
        ai_part = d.get("body_part") if d.get("body_part_source") == "ai" else None
        part, conf, source, note = imaging.reconcile(ai_part, rec["confidence"], dicom_part)
        findings = d.get("text") if png_available and ai_part else (
            meta.get("study_description") or "DICOM image uploaded.")
        merged = imaging.imaging_record(
            part, conf, source,
            modality=imaging.dicom_modality(meta),
            laterality=imaging.dicom_laterality(meta) or d.get("laterality", ""),
            view=meta.get("view_position") or d.get("view", ""),
            findings=findings,
            note=note,
        )
        merged["details"]["dicom_body_part_examined"] = meta.get("body_part_examined", "")
        rec.update(merged)
        rec["record_date"] = _study_date(meta)
    return records


@router.post("/upload", response_model=schemas.DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("prescription"),
    allow_duplicate: bool = Form(False),   # "Upload anyway" after the duplicate warning
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    # Validate document type is one of the allowed types
    if document_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported document type '{document_type}'. Allowed: 'prescription' or 'lab_report'.",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (15 MB max).")

    file_name = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"
    is_dicom = imaging.is_dicom(content, content_type, file_name)
    if is_dicom:
        content_type = "application/dicom"  # browsers send .dcm as octet-stream
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{content_type}'. Upload a JPEG, PNG, WEBP, PDF or DICOM (.dcm) file.",
        )

    # The identical file again? Say so before spending an AI call on it.
    digest = duplicates.sha256(content)
    earlier = duplicates.find_same_file(db, patient.id, digest)
    db.commit()  # keep hashes computed for older uploads
    if earlier and not allow_duplicate:
        raise HTTPException(status_code=409, detail={
            "code": "duplicate_upload",
            "message": f"You already uploaded this exact file (\"{earlier.file_name}\") on "
                       f"{earlier.upload_date:%d %b %Y}. Its records are already in MediPass.",
            "document_id": earlier.id,
            "file_name": earlier.file_name,
            "uploaded_at": earlier.upload_date.isoformat(),
        })

    resolved_type = "lab_report" if is_dicom else document_type
    dicom_meta, dicom_png = {}, None
    if is_dicom:
        try:
            dicom_png, dicom_meta = imaging.read_dicom(content)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"This DICOM file could not be read ({str(e)[:80]}).")

    # Gemini can't read DICOM; send it the rendered PNG instead.
    ai_bytes, ai_mime = (dicom_png, "image/png") if is_dicom else (content, content_type)

    try:
        if is_dicom and not ai_bytes:
            raise RuntimeError("DICOM pixel data could not be decoded")
        _, extracted = extract_medical_records(ai_bytes, ai_mime, date.today(), resolved_type)
        raw_text = "Text extraction handled directly by LLM."
    except Exception as llm_err:
        llm_error_msg = str(llm_err).split(".", 1)[0][:80]
        print(f"LLM Extraction failed: {llm_error_msg}")

        if is_dicom:
            print("DICOM upload: using metadata only")
            extracted = []
            raw_text = "DICOM metadata only (AI unavailable)."
        else:
            print("Falling back to local OCR...")
            from ..ocr import run_ocr, OCRUnavailableError
            from ..extraction import extract_records

            try:
                lines = run_ocr(content, content_type, file_name)
            except OCRUnavailableError as ocr_err:
                print(f"BOTH extraction paths failed - LLM: {llm_error_msg} | OCR: {ocr_err}")
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Document extraction is temporarily unavailable. "
                        "The AI service and the local OCR engine both failed. "
                        "Please try uploading again in a few minutes. "
                        "If the problem persists, contact support."
                    ),
                )

            raw_text = "\n".join(l.text for l in lines)
            words = [w for w in raw_text.split() if sum(c.isalpha() for c in w) >= 3]
            looks_like_image_study = (
                content_type.startswith("image/")
                and resolved_type == "lab_report"
                and len(words) < _MIN_WORDS_FOR_TEXT_DOCUMENT
            )
            if looks_like_image_study:
                # An X-ray/scan photo: there's no text to extract. Use any
                # burned-in label ("CHEST PA") as a hint, otherwise leave the
                # body part for the patient to choose during verification.
                hint = imaging.body_part_from_text(raw_text)
                extracted = [imaging.imaging_record(
                    hint or "unknown", 0.5 if hint else 0.0, "ocr_label" if hint else "none",
                )]
            elif not lines:
                raise HTTPException(status_code=422, detail="No readable text found in this document.")
            else:
                extracted = extract_records(lines, resolved_type, date.today())

    if is_dicom:
        extracted = _apply_dicom(extracted, dicom_meta, png_available=bool(dicom_png))
        raw_text = f"{raw_text}\nDICOM: " + json.dumps({k: v for k, v in dicom_meta.items() if v})

    for item in extracted:
        if "record_date" not in item:
            # no date on the document: use the upload day, flagged as such
            item["record_date"] = date.today()
            item["details"]["is_fallback_date"] = True

    file_path = save_upload(patient.id, file_name, content)

    doc = models.Document(
        patient_id=patient.id,
        uploaded_by=patient.id,
        file_name=file_name,
        document_type=resolved_type,
        file_path=file_path,
        content_type=content_type,
        raw_text=raw_text,
        content_sha256=digest,
    )
    db.add(doc)
    db.flush()  # get doc.id

    for item in extracted:
        record = models.MedicalRecord(
            patient_id=patient.id,
            record_type=item["record_type"],
            title=item["title"],
            details=json.dumps(item["details"]),
            record_date=item["record_date"],
            source_type=models.SourceType.ai_extracted,
            source_document_id=doc.id,
            confidence=item["confidence"],
            verification_status=models.VerificationStatus.unverified,
        )
        db.add(record)

    db.flush()
    if resolved_type == "prescription":
        # A consultation note may have been waiting for this prescription.
        linking.relink_patient(db, patient.id, "prescription uploaded")

    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}", response_model=schemas.DocumentOut)
def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    assert_can_view_patient(db, user, doc.patient_id)
    return doc


@router.get("/{document_id}/file")
def get_document_file(
    document_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Streams back the original uploaded file -- the 'View source' feature
    that makes every extracted fact traceable back to its origin document."""
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    assert_can_view_patient(db, user, doc.patient_id)

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No stored file for this document.")

    try:
        content = read_upload(doc.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The stored file is missing on disk.")

    # Browsers can't display DICOM -- render it to PNG for "View source".
    # The original .dcm stays stored untouched.
    if doc.content_type == "application/dicom":
        try:
            png, _ = imaging.read_dicom(content)
        except Exception:
            png = None
        if png:
            return Response(content=png, media_type="image/png")

    return Response(content=content, media_type=doc.content_type or "application/octet-stream")


class PrescriberIn(BaseModel):
    doctor_name: str = ""
    hospital_name: str = ""


def _clean_name(value: str, doctor: bool) -> str:
    value = " ".join((value or "").split())[:120]
    if doctor and value and not value.lower().startswith("dr"):
        value = f"Dr. {value}"
    return value


@router.patch("/{document_id}/prescriber")
def set_prescriber(
    document_id: str,
    payload: PrescriberIn,
    db: Session = Depends(get_db),
    patient: models.User = Depends(auth.require_role(models.UserRole.patient)),
):
    """
    The patient fills in or corrects who wrote a prescription and where --
    many prescriptions (handwritten, online consults) have no letterhead the
    AI can read, and without a doctor's name linking can't work. Applies to
    every record from the document, then re-runs linking. Locked once a
    consultation link to this prescription has been confirmed.
    """
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc or doc.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.document_type != "prescription":
        raise HTTPException(status_code=400, detail="Only prescriptions have a prescribing doctor.")
    confirmed = db.query(models.RecordLink).filter(
        models.RecordLink.document_id == doc.id, models.RecordLink.status == "confirmed").first()
    if confirmed:
        raise HTTPException(status_code=409, detail="A confirmed link uses this prescription, so its doctor can't be changed.")
    doctor = _clean_name(payload.doctor_name, doctor=True)
    hospital = _clean_name(payload.hospital_name, doctor=False)
    if doctor and len(doctor) < 6:
        raise HTTPException(status_code=400, detail="Enter the doctor's name as written, e.g. Dr. R. Mehta.")

    for r in db.query(models.MedicalRecord).filter(models.MedicalRecord.source_document_id == doc.id):
        details = json.loads(r.details) if r.details else {}
        if not isinstance(details, dict):
            details = {"text": str(details)}
        for key, value in (("doctor_name", doctor), ("hospital_name", hospital)):
            if value:
                details[key] = value
            else:
                details.pop(key, None)
        details["prescriber_source"] = "patient"
        r.details = json.dumps(details)
    db.add(models.AuditLog(patient_id=patient.id, actor_id=patient.id, action="prescriber_edited",
                           target_type="document", target_id=doc.id))
    db.flush()

    # Re-match: unsettled notes, plus proposals that pointed at this prescription.
    linking.relink_patient(db, patient.id, "prescriber edited")
    for link in db.query(models.RecordLink).filter(
            models.RecordLink.document_id == doc.id, models.RecordLink.method == "auto",
            models.RecordLink.status == "linked"):
        note = db.query(models.MedicalRecord).filter(models.MedicalRecord.id == link.consultation_id).first()
        if note:
            linking.link_consultation(db, note, "prescriber edited")
    db.commit()
    return {"document_id": doc.id, "doctor_name": doctor, "hospital_name": hospital}
