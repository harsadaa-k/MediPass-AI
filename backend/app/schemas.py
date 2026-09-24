from datetime import date, datetime
from typing import Optional, List, Any

from pydantic import BaseModel, EmailStr

from .models import UserRole, SourceType, VerificationStatus, RecordType, AccessStatus


# ---------- Auth ----------

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    is_email_verified: bool
    # register only: False when the verification email couldn't be sent
    verification_email_sent: Optional[bool] = None

    class Config:
        from_attributes = True


class VerifyEmailIn(BaseModel):
    token: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Documents ----------
# Upload is multipart/form-data (file + document_type), handled directly by
# FastAPI's UploadFile/Form params in the router -- no JSON body schema
# needed for the request. DocumentOut below is still used for the response.

class DocumentOut(BaseModel):
    id: str
    patient_id: str
    file_name: str
    document_type: str
    upload_date: datetime

    class Config:
        from_attributes = True


# ---------- Medical records ----------

class MedicalRecordOut(BaseModel):
    id: str
    patient_id: str
    record_type: RecordType
    title: str
    details: Any            # parsed JSON dict, not the raw string
    record_date: date
    source_type: SourceType
    source_document_id: Optional[str] = None
    created_by: Optional[str] = None
    confidence: Optional[float] = None
    verification_status: VerificationStatus
    # record_date = consultation/report date (from the document or entered by
    # the doctor); logged_at = when the record was added to MediPass.
    logged_at: Optional[datetime] = None
    # Medications only: {duration, duration_days, start_date, end_date, ongoing}
    # (see app/durations.py). None when the prescription gives no duration.
    course: Optional[dict] = None
    # Verify queue only: the timeline record this one appears to repeat
    # ({id, title, record_date, logged_at}); see app/duplicates.py.
    duplicate_of: Optional[dict] = None

    class Config:
        from_attributes = True


class RecordVerifyIn(BaseModel):
    # if corrected_details is omitted, the record is confirmed as-is
    corrected_details: Optional[dict] = None
    corrected_title: Optional[str] = None
    corrected_record_date: Optional[date] = None  # consultation/report date


class ConsultationIn(BaseModel):
    patient_id: str
    record_type: RecordType
    title: str
    details: dict
    record_date: date


# ---------- Access / consent ----------

class AccessRequestIn(BaseModel):
    patient_id: str


class AccessRespondIn(BaseModel):
    approve: bool
    scope: List[str] = []
    expiry_days: int = 30


class AccessGrantOut(BaseModel):
    id: str
    patient_id: str
    provider_id: str
    status: str
    scope: List[str]
    requested_at: datetime
    responded_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    patient_name: Optional[str] = None
    patient_email: Optional[str] = None
    provider_name: Optional[str] = None
    provider_email: Optional[str] = None
    provider_specialty: Optional[str] = None
    provider_hospital: Optional[str] = None
    provider_verified: bool = False

    class Config:
        from_attributes = True


class PatientQRCreateIn(BaseModel):
    scope: List[str] = ["medications", "allergies", "diagnoses"]
    access_days: int = 30        # how long the doctor keeps access after scanning
    valid_minutes: int = 15      # how long the QR code itself can be scanned


class PatientQROut(BaseModel):
    id: str
    token: Optional[str] = None  # only returned once, when the code is created
    scope: List[str]
    access_days: int
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    used_by_name: Optional[str] = None
    revoked: bool = False
    outcome: Optional[str] = None  # "added" | "already_patient" once scanned


class PatientQRRedeemIn(BaseModel):
    code: str  # the scanned text: a full /add-patient/<token> URL or the bare token


class PatientQRRedeemOut(BaseModel):
    grant_id: str
    patient_id: str
    patient_name: str
    patient_email: str
    scope: List[str]
    expires_at: Optional[datetime] = None
    already_had_access: bool


class ProviderProfileUpdate(BaseModel):
    specialty: Optional[str] = None
    hospital_name: Optional[str] = None

class PatientLookupOut(BaseModel):
    id: str
    email: str
    full_name: str

    class Config:
        from_attributes = True


class BadgesOut(BaseModel):
    pending_access_requests: int
    unverified_records: int
    unread_notifications: int = 0
    pending_links: int = 0  # document links awaiting the patient's confirmation


class NotificationOut(BaseModel):
    id: str
    patient_id: str
    message: str
    related_record_id: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

# ---------- Timeline ----------

class TimelineFlag(BaseModel):
    type: str          # "conflict"
    message: str
    record_ids: List[str] = []


class TimelineOut(BaseModel):
    records: List[MedicalRecordOut]
    flags: List[TimelineFlag]


# ---------- Audit ----------

class AuditLogOut(BaseModel):
    id: str
    actor_id: str
    actor_name: Optional[str] = None
    actor_role: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True
