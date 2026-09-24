"""
Entity extraction from OCR'd text.

Takes real OCR output (app/ocr.py's OCRLine list, each with a genuine
per-line confidence from Tesseract or 1.0 for embedded PDF text) and pulls
out structured medical entities: medications, allergies, diagnoses, lab
results (lab reports) and generic consultation notes. This is the fallback
path -- documents.py only uses it when Gemini extraction fails (quota,
outage, bad key).

This is still rule-based (regex + keyword matching), not a trained medical
NER model -- that's a real limitation, not hidden: see README "What's
still simplified". What IS real now is the OCR itself and the confidence
scores, which used to be faked. This function is the one remaining clean
swap point if you plug in a real medical-NER model or an LLM extraction
call later -- everything downstream (routers, models, frontend) only cares
about the dict shape returned here.
"""
import re
from datetime import date
from typing import List, Dict, Any
from dateutil.parser import parse as parse_date

from .confidence import score as score_confidence
from .ocr import OCRLine

# A dose like "500mg" -- but not a lab concentration like "98 mg/dL".
_DOSE_PATTERN = re.compile(r"\d+(?:\.\d+)?\s?(?:mg|ml|mcg|iu)\b(?!\s*/)", re.IGNORECASE)
_MED_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z\-]{2,})\s+(\d+(?:\.\d+)?\s?(?:mg|ml|mcg|iu))\b(?!\s*/)", re.IGNORECASE
)

# Letterhead / boilerplate lines that shouldn't become records on their own.
_HEADER_PATTERNS = [
    r"^\s*(page|pg)\.?\s*\d",          # page numbers
    r"^\s*\d{5,}",                      # long numeric IDs
    r"tel[:\.]|phone[:\.]|fax[:\.]",    # phone/fax lines
    r"www\.|http|\.com|\.org",           # URLs
    r"^\s*(dr|doctor)\.?\s+\w+",        # doctor name lines
    r"\b(mbbs|frcs|mrcp)\b",            # doctor qualifications in a letterhead
    r"^\s*date\s*[:.]",                  # date labels
    r"^\s*patient\s*(name|id)?\s*[:.]",  # patient header labels
    r"reg(istration)?\s*(no|number)",    # registration numbers
]


def _is_header(lower: str) -> bool:
    return any(re.search(pat, lower) for pat in _HEADER_PATTERNS)


_DOCTOR_NAME = re.compile(r"\b(?:Dr|Doctor)\.?\s+((?:[A-Z]\.\s*)*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")


def find_doctor_name(lines: List[OCRLine]) -> str:
    """'City Clinic - Dr. R. Mehta, MBBS' -> 'Dr. R. Mehta' (first match wins)."""
    for line in lines:
        m = _DOCTOR_NAME.search(line.text)
        if m:
            return f"Dr. {m.group(1).strip()}"
    return ""


_HOSPITAL_WORDS = re.compile(
    r"\b(hospitals?|clinics?|nursing home|medical (?:centre|center|college)|health ?care|polyclinic|dispensary)\b",
    re.IGNORECASE,
)


def find_hospital_name(lines: List[OCRLine]) -> str:
    """First letterhead-style line naming a hospital/clinic, e.g.
    'City Clinic  -  Dr. R. Mehta' -> 'City Clinic'."""
    for line in lines[:8]:  # letterheads are at the top
        text = line.text.strip()
        if not _HOSPITAL_WORDS.search(text):
            continue
        name = re.split(r"\s+[-\u2013|]\s+|,\s+|\s{2,}", text)[0].strip(" -|,")
        name = re.split(r"\b(?:Dr|Doctor)\.?\s", name)[0].strip(" -|,")
        if len(name) >= 4:
            return name.title() if name.isupper() else name
    return ""


def _after_colon(text: str) -> str:
    """'Diagnosis: Acute pharyngitis' -> 'Acute pharyngitis'."""
    return text.split(":", 1)[1].strip() if ":" in text else ""


def extract_records(lines: List[OCRLine], document_type: str, fallback_date: date) -> List[Dict[str, Any]]:
    """
    Returns a list of dicts shaped like:
      {"record_type": ..., "title": ..., "details": {...},
       "record_date": date, "confidence": float}
    """
    results = []

    record_date = fallback_date
    is_fallback_date = True
    for line in lines:
        try:
            # dayfirst: "12/10/22" on these documents is 12 Oct 2022, not Dec 10
            parsed = parse_date(line.text, fuzzy=True, dayfirst=True)
            if 1900 < parsed.year <= date.today().year + 1:
                record_date = parsed.date()
                is_fallback_date = False
                break
        except (ValueError, OverflowError):
            continue

    doctor_name = find_doctor_name(lines)
    hospital_name = find_hospital_name(lines)

    def add(record_type, title, details, confidence):
        extra = {"doctor_name": doctor_name} if doctor_name else {}
        if hospital_name:
            extra["hospital_name"] = hospital_name
        details = {**details, **extra, "is_fallback_date": is_fallback_date}
        # OCR legibility of the line, adjusted by the same field checks as
        # the AI path (app/confidence.py).
        confidence, details["confidence_basis"] = score_confidence(
            record_type, title, details, confidence, "OCR legibility", not is_fallback_date)
        results.append({
            "record_type": record_type,
            "title": title[:120],
            "details": details,
            "record_date": record_date,
            "confidence": confidence,
        })

    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        lower = text.lower()
        confidence = line.confidence

        if "aller" in lower:
            what = _after_colon(text)
            add("allergy", f"Allergy: {what}" if what else "Allergy noted in document",
                {"text": text}, confidence)

        elif re.search(r"\bdiagnos(is|ed|es)\b", lower):  # not "diagnostics"
            what = _after_colon(text)
            add("diagnosis", what[:1].upper() + what[1:] if what else "Diagnosis noted in document",
                {"text": text}, confidence)

        elif document_type == "lab_report" and not _is_header(lower) and (
            re.match(r"^\s*test\s*(name)?\s*:", lower)
            or (":" in text and re.search(r"\d", _after_colon(text)))
        ):
            # "Test: Complete Blood Count"  or  "Hemoglobin: 12.1 g/dL (reference 13-17)"
            if re.match(r"^\s*test\s*(name)?\s*:", lower):
                title = _after_colon(text)
            else:
                title = text.split(":", 1)[0].strip()
            add("lab_result", title or "Lab result", {"text": text}, confidence)

        elif _DOSE_PATTERN.search(lower):
            match = _MED_PATTERN.search(text)
            name = match.group(1) if match else text.split()[0]
            dose = match.group(2) if match else "unknown dose"
            add("medication", f"{name} {dose}",
                {"raw_line": text, "medicine": name, "dose": dose, "frequency": "", "duration": ""},
                confidence)

        else:
            # ---- Minimum-content filter for the generic consultation fallback ----
            # Skip lines too short to carry meaningful clinical content
            if len(text.split()) < 4:
                continue
            # Skip lines that are purely numbers/punctuation (page numbers, IDs, etc.)
            if len(re.sub(r"[^a-zA-Z]", "", text)) < 3:
                continue
            # Skip common header/letterhead/boilerplate lines
            if _is_header(lower):
                continue
            # All-caps banner lines ("CITYLAB DIAGNOSTICS")
            if text.isupper():
                continue

            add("consultation", f"Note from {document_type.replace('_', ' ')}", {"text": text}, confidence)

    return results
