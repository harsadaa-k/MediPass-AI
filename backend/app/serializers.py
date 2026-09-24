import json
from . import models, schemas
from .durations import medication_course
from .imaging import describe_image, is_placeholder_text, normalize_view


def record_to_out(record: models.MedicalRecord) -> schemas.MedicalRecordOut:
    details = json.loads(record.details)
    if isinstance(details, dict) and "view" in details and "body_part" in details:
        # imaging projection: records saved before normalize_view existed can
        # hold a runaway model string -- show only a real projection name
        view = normalize_view(details["view"])
        if view:
            details["view"] = view
        else:
            details.pop("view")
    if isinstance(details, dict) and "body_part" in details and is_placeholder_text(details.get("text")):
        # imaging record saved with the stand-in text: describe it instead
        details["text"] = describe_image(details.get("modality", "xray"), details["body_part"], details.get("view", ""))
    # Treatment course (duration in days, end date) is derived on read, so it
    # follows any correction the patient makes to the date or the duration.
    course = (medication_course(details, record.record_date)
              if record.record_type == models.RecordType.medication else None)
    return schemas.MedicalRecordOut(
        id=record.id,
        patient_id=record.patient_id,
        record_type=record.record_type,
        title=record.title,
        details=details,
        record_date=record.record_date,
        source_type=record.source_type,
        source_document_id=record.source_document_id,
        created_by=record.created_by,
        confidence=record.confidence,
        verification_status=record.verification_status,
        logged_at=record.created_at,
        course=course,
    )
