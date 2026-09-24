"""
Regenerates the sample documents used by docs/DEMO_SCRIPT.md.

Run from the backend venv (needs Pillow + PyMuPDF):
    backend/venv/Scripts/python.exe docs/demo-documents/make_samples.py

All names and values are fictional.
"""
import os

import pymupdf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))


def _font(size):
    for name in ("arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def prescription_png():
    img = Image.new("RGB", (900, 560), "white")
    d = ImageDraw.Draw(img)
    big, body = _font(30), _font(24)
    d.text((40, 30), "City Clinic  -  Dr. R. Mehta, MBBS", fill="black", font=big)
    d.text((40, 80), "Date: 2026-09-20", fill="black", font=body)
    d.text((40, 115), "Patient: Demo Patient", fill="black", font=body)
    d.line((40, 160, 860, 160), fill="black", width=2)
    lines = [
        "Rx",
        "1. Amoxicillin 500mg   1-0-1   after food   x 5 days",
        "2. Paracetamol 650mg   SOS for fever",
        "3. Cetirizine 10mg   0-0-1   x 3 days",
        "Known allergy: Sulfa drugs",
        "Diagnosis: Acute pharyngitis",
    ]
    for i, text in enumerate(lines):
        d.text((40, 185 + i * 52), text, fill="black", font=body)
    img.save(os.path.join(HERE, "prescription.png"))


def _pdf(path, lines):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for text in lines:
        size = 16 if text.isupper() else 11
        page.insert_text((60, y), text, fontsize=size)
        y += 26 if size == 16 else 18
    doc.save(path)
    doc.close()


def lab_report_pdf():
    _pdf(os.path.join(HERE, "lab_report.pdf"), [
        "CITYLAB DIAGNOSTICS",
        "Patient: Demo Patient        Sample collected: 2026-08-14",
        "Test: Complete Blood Count (CBC)",
        "Hemoglobin: 12.1 g/dL        (reference 13.0 - 17.0)   LOW",
        "WBC count: 11,800 /uL        (reference 4,000 - 11,000)   HIGH",
        "Platelets: 2.4 lakh /uL      (reference 1.5 - 4.0)",
        "Test: Fasting Blood Sugar",
        "Glucose (fasting): 98 mg/dL  (reference 70 - 100)",
        "Remarks: Mild anaemia and leucocytosis; correlate clinically.",
    ])


if __name__ == "__main__":
    prescription_png()
    lab_report_pdf()
    print("wrote prescription.png, lab_report.pdf to", HERE)
