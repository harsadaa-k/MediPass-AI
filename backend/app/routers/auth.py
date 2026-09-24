import os
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import models, schemas, auth, email_utils

_SKIP_EMAIL_VERIFICATION = os.environ.get("MEDIPASS_SKIP_EMAIL_VERIFICATION", "false").lower() == "true"
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

RESEND_COOLDOWN_SECONDS = 60
_last_resend = {}  # email -> time of the last resend (per process; enough to stop hammering)


@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(payload: schemas.UserRegister, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing and existing.is_email_verified:
        raise HTTPException(status_code=400, detail="Email already registered. Log in, or use Forgot password.")
    if existing:
        # Signed up before but never verified (e.g. the email didn't arrive).
        if _has_data(db, existing):
            # Never overwrite an account that's in use: just send the link again.
            if not existing.verification_token:
                existing.verification_token = secrets.token_urlsafe(32)
                db.commit()
            sent = email_utils.send_verification_email(existing.email, existing.verification_token)
            raise HTTPException(status_code=409, detail={
                "code": "unverified_exists",
                "email_sent": sent,
                "message": "This email is already registered but not verified yet. "
                           + ("We've sent the verification link again." if sent
                              else "We couldn't send the verification email; try Resend in a minute."),
            })
        # Nothing depends on it yet: start the sign-up again with the new details.
        return _restart_signup(db, existing, payload)

    token = secrets.token_urlsafe(32)
    user = models.User(
        email=payload.email,
        hashed_password=auth.hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_email_verified=False,
        verification_token=token
    )
    db.add(user)
    db.flush()  # get user.id before creating the profile row

    if payload.role == models.UserRole.patient:
        db.add(models.PatientProfile(user_id=user.id))
    else:
        db.add(models.ProviderProfile(user_id=user.id))

    db.commit()
    db.refresh(user)
    
    # Send real verification email; tell the app if it failed so it can offer "Resend"
    sent = email_utils.send_verification_email(user.email, token)
    out = schemas.UserOut.model_validate(user)
    out.verification_email_sent = sent
    return out


def _has_data(db: Session, user: models.User) -> bool:
    """Does anything already hang off this account?"""
    return any(q.first() is not None for q in (
        db.query(models.AccessGrant.id).filter((models.AccessGrant.patient_id == user.id) | (models.AccessGrant.provider_id == user.id)),
        db.query(models.Document.id).filter(models.Document.patient_id == user.id),
        db.query(models.MedicalRecord.id).filter((models.MedicalRecord.patient_id == user.id) | (models.MedicalRecord.created_by == user.id)),
        db.query(models.DoctorCredential.id).filter(models.DoctorCredential.provider_id == user.id),
    ))


def _restart_signup(db: Session, user: models.User, payload: schemas.UserRegister):
    """Re-registering an unverified, unused account replaces its details."""
    user.hashed_password = auth.hash_password(payload.password)
    user.full_name = payload.full_name
    if user.role != payload.role:
        db.query(models.PatientProfile).filter(models.PatientProfile.user_id == user.id).delete()
        db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == user.id).delete()
        db.add(models.PatientProfile(user_id=user.id) if payload.role == models.UserRole.patient
               else models.ProviderProfile(user_id=user.id))
        user.role = payload.role
    # Keep the existing link: emails that already went out must keep working.
    user.verification_token = user.verification_token or secrets.token_urlsafe(32)
    db.commit()
    db.refresh(user)
    sent = email_utils.send_verification_email(user.email, user.verification_token)
    out = schemas.UserOut.model_validate(user)
    out.verification_email_sent = sent
    return out


@router.post("/resend-verification")
def resend_verification(payload: schemas.ForgotPasswordIn, db: Session = Depends(get_db)):
    """Send the verification link again (same link, so an older email still works)."""
    now = time.monotonic()
    wait = RESEND_COOLDOWN_SECONDS - (now - _last_resend.get(payload.email, -1e9))
    if wait > 0:
        raise HTTPException(status_code=429, detail=f"Please wait {int(wait) + 1} seconds before asking again.")
    _last_resend[payload.email] = now
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user and not user.is_email_verified:
        if not user.verification_token:
            user.verification_token = secrets.token_urlsafe(32)
            db.commit()
        if not email_utils.send_verification_email(user.email, user.verification_token):
            raise HTTPException(status_code=502, detail="We couldn't send the email right now. Please try again in a few minutes.")
    # Same answer whether or not the account exists (no email enumeration)
    return {"message": "If that account exists and isn't verified yet, a new verification link is on its way."}


@router.post("/verify-email")
def verify_email(payload: schemas.VerifyEmailIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.verification_token == payload.token).first()
    if not user:
        raise HTTPException(status_code=400, detail="This verification link isn't valid any more. "
                                                    "Ask for a new one below.")
    # The token is kept, so opening the link again (or the page loading twice)
    # says "already verified" instead of "invalid". It can only ever verify.
    if user.is_email_verified:
        return {"message": "Your email is already verified. You can log in.", "already_verified": True}
    user.is_email_verified = True
    db.commit()
    return {"message": "Email verified successfully.", "already_verified": False}


@router.post("/forgot-password")
def forgot_password(payload: schemas.ForgotPasswordIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_password_token = token
        db.commit()
        email_utils.send_reset_password_email(user.email, token)
    # Always return a generic success message to prevent email enumeration
    return {"message": "If that email exists, a password reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: schemas.ResetPasswordIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.reset_password_token == payload.token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    
    user.hashed_password = auth.hash_password(payload.new_password)
    user.reset_password_token = None
    user.is_email_verified = True
    user.verification_token = None
    db.commit()
    return {"message": "Password reset successfully."}


@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    
    if not _SKIP_EMAIL_VERIFICATION and not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox for the verification link.",
        )

    token = auth.create_access_token(subject=user.id)
    return schemas.Token(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@router.put("/profile/provider", status_code=200)
def update_provider_profile(
    payload: schemas.ProviderProfileUpdate,
    db: Session = Depends(get_db),
    provider: models.User = Depends(auth.require_role(models.UserRole.provider)),
):
    profile = db.query(models.ProviderProfile).filter(models.ProviderProfile.user_id == provider.id).first()
    if not profile:
        profile = models.ProviderProfile(user_id=provider.id)
        db.add(profile)
    
    if payload.specialty is not None:
        profile.specialty = payload.specialty
    if payload.hospital_name is not None:
        profile.hospital_name = payload.hospital_name
        
    db.commit()
    db.refresh(profile)
    return {"status": "success", "specialty": profile.specialty, "hospital_name": profile.hospital_name}
