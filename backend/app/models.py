"""
ORM models.

Design notes (tied to REQUIREMENTS.md):
- MedicalRecord always carries source_type + (source_document_id or created_by),
  per NFR-2/NFR-3 -- there is no such thing as a record with no provenance.
- verification_status distinguishes AI-extracted-but-unverified data from
  anything a human (patient or provider) has confirmed, per FR-2.3/NFR-7.
"""
import enum
import uuid
from datetime import datetime, date

from sqlalchemy import (
    Column, String, DateTime, Date, ForeignKey, Float, Enum, Text, Boolean, Integer, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id() -> str:
    return uuid.uuid4().hex


class UserRole(str, enum.Enum):
    patient = "patient"
    provider = "provider"


class SourceType(str, enum.Enum):
    patient_provided = "patient_provided"
    ai_extracted = "ai_extracted"
    doctor_generated = "doctor_generated"
    hospital_generated = "hospital_generated"
    lab_generated = "lab_generated"


class VerificationStatus(str, enum.Enum):
    unverified = "unverified"
    patient_verified = "patient_verified"
    provider_verified = "provider_verified"
    conflict = "conflict"


class RecordType(str, enum.Enum):
    medication = "medication"
    lab_result = "lab_result"
    diagnosis = "diagnosis"
    consultation = "consultation"
    hospitalization = "hospitalization"
    allergy = "allergy"


class AccessStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    denied = "denied"
    revoked = "revoked"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    is_email_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String, nullable=True)
    reset_password_token = Column(String, nullable=True)

    patient_profile = relationship("PatientProfile", back_populates="user", uselist=False)
    provider_profile = relationship("ProviderProfile", back_populates="user", uselist=False)


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    blood_group = Column(String, nullable=True)
    emergency_contact = Column(String, nullable=True)

    user = relationship("User", back_populates="patient_profile")


class ProviderProfile(Base):
    __tablename__ = "provider_profiles"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    specialty = Column(String, nullable=True)
    hospital_name = Column(String, nullable=True)

    user = relationship("User", back_populates="provider_profile")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=False)
    file_name = Column(String, nullable=False)
    document_type = Column(String, nullable=False)  # prescription / lab_report (legacy rows may say discharge_summary)
    file_path = Column(String, nullable=True)        # where the original upload is stored on disk
    content_type = Column(String, nullable=True)      # image/jpeg, application/pdf, etc.
    raw_text = Column(Text, nullable=True)           # full OCR'd (or embedded-PDF) text of the upload
    content_sha256 = Column(String, nullable=True, index=True)  # spots re-uploads of the identical file
    upload_date = Column(DateTime, default=datetime.utcnow)


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)

    record_type = Column(Enum(RecordType), nullable=False)
    title = Column(String, nullable=False)
    details = Column(Text, nullable=False)   # JSON-encoded structured fields
    record_date = Column(Date, nullable=False)

    source_type = Column(Enum(SourceType), nullable=False)
    source_document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)  # provider id, if doctor-generated

    confidence = Column(Float, nullable=True)  # only meaningful for ai_extracted records
    verification_status = Column(Enum(VerificationStatus), nullable=False,
                                  default=VerificationStatus.unverified)

    created_at = Column(DateTime, default=datetime.utcnow)


class AccessGrant(Base):
    __tablename__ = "access_grants"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider_id = Column(String, ForeignKey("users.id"), nullable=False)

    status = Column(Enum(AccessStatus), nullable=False, default=AccessStatus.pending)
    scope = Column(Text, nullable=False, default="[]")  # JSON list, e.g. ["medications","labs"]

    requested_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class PatientQRCode(Base):
    """
    A patient's "add me as your patient" QR code. Showing it to a doctor is
    the patient's consent: the doctor who scans it gets an approved access
    grant with the scope/duration the patient chose -- no request/approval
    round-trip. Single use, short-lived, and only a SHA-256 hash of the
    secret token is stored.
    """
    __tablename__ = "patient_qr_codes"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    scope = Column(Text, nullable=False, default="[]")  # JSON list, same values as AccessGrant.scope
    access_days = Column(Integer, nullable=False, default=30)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    used_by = Column(String, ForeignKey("users.id"), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)


class DoctorCredential(Base):
    """
    What a provider submits to prove they're a real, registered doctor.
    status: pending -> verified | rejected (set by a reviewer, see
    backend/review_doctors.py). Specialty and hospital live on
    ProviderProfile and are part of what's reviewed.
    """
    __tablename__ = "doctor_credentials"

    id = Column(String, primary_key=True, default=gen_id)
    provider_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    registration_number = Column(String, nullable=False)
    medical_council = Column(String, nullable=False)   # e.g. "National Medical Commission", "Karnataka Medical Council"
    qualification = Column(String, nullable=False)     # e.g. "MBBS, MD (Psychiatry)"
    registration_year = Column(Integer, nullable=True)
    # JSON list of {"degree", "institution", "year"}, e.g. MBBS, AIIMS Delhi, 2010
    education = Column(Text, nullable=True)
    # JSON list of other hospitals/institutions besides ProviderProfile.hospital_name
    affiliations = Column(Text, nullable=True)
    practice_start_year = Column(Integer, nullable=True)  # for years of experience
    certificate_path = Column(String, nullable=True)
    certificate_file_name = Column(String, nullable=True)
    certificate_content_type = Column(String, nullable=True)

    status = Column(String, nullable=False, default="pending")
    submitted_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewer = Column(String, nullable=True)
    review_note = Column(Text, nullable=True)


class RecordLink(Base):
    """
    Link between a doctor's consultation note and the patient-uploaded
    prescription (Document) written by the same doctor. One row per
    consultation holds its *current* link state; every change is also in
    audit_logs.

    status:  linked     -> document_id set
             ambiguous  -> several equally good prescriptions (candidate_document_ids)
             unmatched  -> no prescription from that doctor (yet)
    method:  auto | manual  (manual rows are never changed by the auto-linker)
    """
    __tablename__ = "record_links"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    consultation_id = Column(String, ForeignKey("medical_records.id"), nullable=False, unique=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=True, index=True)

    status = Column(String, nullable=False)
    method = Column(String, nullable=False, default="auto")
    score = Column(Float, nullable=True)
    match_reason = Column(Text, nullable=True)
    candidate_document_ids = Column(Text, nullable=False, default="[]")  # JSON list

    process = Column(String, nullable=True)       # which system step made it, e.g. "auto-linker v1 (consultation added)"
    created_by = Column(String, ForeignKey("users.id"), nullable=True)  # user for manual overrides
    override_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    related_record_id = Column(String, ForeignKey("medical_records.id"), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PatientStatusFlag(Base):
    """
    A doctor's own status for one of their patients on the Active Patients
    list (critical / follow_up / ongoing / new). Without a row the status is
    worked out automatically (routers/provider_patients.py).
    """
    __tablename__ = "patient_status_flags"
    __table_args__ = (UniqueConstraint("provider_id", "patient_id"),)

    id = Column(String, primary_key=True, default=gen_id)
    provider_id = Column(String, ForeignKey("users.id"), nullable=False)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
