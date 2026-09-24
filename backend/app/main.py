import os
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models
from .database import engine, Base, add_missing_columns
from .llm import require_gemini_key

# Fail at startup (not on the first upload) if the Gemini key is missing.
require_gemini_key()
from .routers import auth, documents, records, timeline, access, consultations, audit, users, notifications, patient_qr, links, doctor_verification, provider_patients, reviewer

# Dev convenience: create tables on startup. For a real deployment you'd use
# Alembic migrations instead of create_all.
Base.metadata.create_all(bind=engine)
add_missing_columns(["doctor_credentials", "documents"])  # new nullable columns on existing tables

# Seed demo accounts for hackathon demos (idempotent — skips if they exist).
# Their passwords are in the public repo, so a public deployment should set
# MEDIPASS_SEED_DEMO=false.
if os.environ.get("MEDIPASS_SEED_DEMO", "true").lower() == "true":
    from seed_demo_data import seed_demo_data
    seed_demo_data()

app = FastAPI(
    title="MediPass API",
    description="Patient-controlled, source-traceable medical history platform — prototype backend.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # Comma-separated override, e.g. to serve the frontend on a LAN IP for phone scanning.
    allow_origins=[o.strip() for o in os.environ.get(
        "MEDIPASS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(records.router)
app.include_router(timeline.router)
app.include_router(access.router)
app.include_router(consultations.router)
app.include_router(audit.router)
app.include_router(users.router)
app.include_router(notifications.router)
app.include_router(patient_qr.router)
app.include_router(links.router)
app.include_router(doctor_verification.router)
app.include_router(provider_patients.router)
app.include_router(reviewer.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
