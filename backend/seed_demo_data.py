"""
Seed script: inserts pre-verified demo accounts for hackathon demonstrations.

Called automatically from main.py on startup.  Idempotent — skips if the
accounts already exist.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app import models
from app.auth import hash_password
from app.database import SessionLocal


def seed_demo_data() -> None:
    """Insert two demo accounts (patient + provider) if they don't already exist."""
    db: Session = SessionLocal()
    try:
        # ---- Patient demo account ----
        if not db.query(models.User).filter(models.User.email == "patient@medipass.demo").first():
            patient = models.User(
                email="patient@medipass.demo",
                hashed_password=hash_password("Demo@123"),
                full_name="Demo Patient",
                role=models.UserRole.patient,
                is_email_verified=True,
                verification_token=None,
            )
            db.add(patient)
            db.flush()
            db.add(models.PatientProfile(user_id=patient.id))
            print("SEED: created patient@medipass.demo")

        # ---- Provider demo account ----
        if not db.query(models.User).filter(models.User.email == "doctor@medipass.demo").first():
            doctor = models.User(
                email="doctor@medipass.demo",
                hashed_password=hash_password("Demo@123"),
                full_name="Demo Doctor",
                role=models.UserRole.provider,
                is_email_verified=True,
                verification_token=None,
            )
            db.add(doctor)
            db.flush()
            db.add(models.ProviderProfile(
                user_id=doctor.id,
                specialty="General Physician",
                hospital_name="Demo Medical Center",
            ))
            print("SEED: created doctor@medipass.demo")

        # Demo doctor: pre-verified credentials (see app/routers/doctor_verification.py)
        doctor = db.query(models.User).filter(models.User.email == "doctor@medipass.demo").first()
        if doctor and not db.query(models.DoctorCredential).filter(
            models.DoctorCredential.provider_id == doctor.id
        ).first():
            db.add(models.DoctorCredential(
                provider_id=doctor.id, registration_number="DEMO-00001",
                medical_council="Demo Medical Council", qualification="MBBS", registration_year=2015,
                status="verified", reviewed_at=datetime.utcnow(), reviewer="seed",
                review_note="Demo account",
            ))
            print("SEED: verified doctor@medipass.demo")

        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"SEED ERROR: {exc}")
    finally:
        db.close()
