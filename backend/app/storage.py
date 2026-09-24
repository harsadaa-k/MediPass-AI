"""
Local disk storage for uploaded documents.

Prototype-grade: files live under UPLOAD_ROOT on the same machine as the
backend. Swappable later for S3/GCS by changing just this module -- routers
only call save_upload()/read_upload(), never touch the filesystem directly.
"""
import os
import uuid

UPLOAD_ROOT = os.environ.get("MEDIPASS_UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "uploads"))


def save_upload(patient_id: str, original_filename: str, content: bytes) -> str:
    patient_dir = os.path.join(UPLOAD_ROOT, patient_id)
    os.makedirs(patient_dir, exist_ok=True)

    ext = os.path.splitext(original_filename)[1] or ""
    stored_name = f"{uuid.uuid4().hex}{ext}"
    full_path = os.path.join(patient_dir, stored_name)

    with open(full_path, "wb") as f:
        f.write(content)

    return full_path


def read_upload(file_path: str) -> bytes:
    """Read a stored upload. Stored paths are absolute, so if the project was
    moved/copied to another folder or machine, look the file up by its
    <patient_id>/<name> under the current UPLOAD_ROOT instead."""
    if not os.path.exists(file_path):
        norm = file_path.replace("\\", "/")
        patient_dir, name = os.path.basename(os.path.dirname(norm)), os.path.basename(norm)
        relocated = os.path.join(UPLOAD_ROOT, patient_dir, name)
        if os.path.exists(relocated):
            file_path = relocated
    with open(file_path, "rb") as f:
        return f.read()
