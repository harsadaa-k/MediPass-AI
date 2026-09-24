import os
import json
import re
from google import genai
from google.genai import types
from datetime import date
from typing import List, Dict, Any, Tuple

from .confidence import score as score_confidence
from .durations import format_duration, parse_duration
from .imaging import (
    BODY_PARTS, BODY_PART_CODES, MODALITIES, imaging_title, normalize_body_part, normalize_view,
    describe_image, is_placeholder_text,
)

MAX_FIELD_CHARS = 1500

# ---------- Shared Gemini client ----------
# Fail fast at startup if the key is missing — don't silently fall back to a
# baked-in key that might be revoked or rate-limited.
def require_gemini_key() -> str:
    """Called from main.py at startup so a missing key fails immediately,
    not on the first upload."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set.  Copy backend/.env.example to "
            "backend/.env and fill in your key."
        )
    return key

# One model name for every Gemini call (extraction, scope recommendation,
# voice structuring, timeline summary). Override via env if needed.
GEMINI_MODEL = os.environ.get("MEDIPASS_GEMINI_MODEL", "gemini-3.6-flash")

_client: genai.Client | None = None

def get_gemini_client() -> genai.Client:
    """Return a module-level singleton Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=require_gemini_key())
    return _client


# Tried in order when the primary model is overloaded (503), out of quota
# (429) or not available to this key (404). Comma-separated; "" disables.
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get(
        "MEDIPASS_GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-3.5-flash-lite"
    ).split(",")
    if m.strip() and m.strip() != GEMINI_MODEL
]
_OVERLOAD_RETRY_DELAYS = (1, 3)  # seconds between retries of a 503 on the same model


def _short_error(err: Exception) -> str:
    """'503 UNAVAILABLE. {...huge json...}' -> '503 UNAVAILABLE'"""
    return str(err).split(".", 1)[0].strip()[:60]


def generate_content(contents, config=None, *, purpose: str = "Gemini"):
    """
    Every Gemini call goes through here. For each model (primary, then the
    fallbacks):
      * 503 UNAVAILABLE ("model is overloaded") -> short retries, then next model
      * 429 per-minute quota                     -> next model
      * 429 per-day quota / 404 model not found  -> next model immediately
      * anything else (bad key, bad request)     -> raise immediately
    Raises the last error if every model fails; callers have their own
    non-AI fallback.
    """
    import time

    # We never use function calling; disabling it also silences the SDK's
    # "Direct use of automatic function calling (AFC)..." warning.
    if config is None:
        config = types.GenerateContentConfig()
    config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)

    last_err = None
    for model in [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
        for attempt in range(len(_OVERLOAD_RETRY_DELAYS) + 1):
            try:
                response = get_gemini_client().models.generate_content(
                    model=model, contents=contents, config=config,
                )
                if model != GEMINI_MODEL or attempt:
                    print(f"{purpose}: succeeded on {model} (attempt {attempt + 1})")
                return response
            except Exception as e:
                last_err = e
                s = str(e)
                overloaded = "503" in s or "UNAVAILABLE" in s
                model_missing = "404" in s or "NOT_FOUND" in s
                rate_limited = "429" in s or "RESOURCE_EXHAUSTED" in s
                if overloaded and attempt < len(_OVERLOAD_RETRY_DELAYS):
                    delay = _OVERLOAD_RETRY_DELAYS[attempt]
                    print(f"{purpose}: {model} overloaded (503), retrying in {delay}s")
                    time.sleep(delay)
                    continue
                if overloaded or model_missing or rate_limited:
                    print(f"{purpose}: {model} unavailable ({_short_error(e)}), trying next model")
                    break
                raise
    raise last_err if last_err else RuntimeError("No Gemini model configured")

# Define the expected JSON schema for Gemini's structured output
extraction_schema = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "enum": ["prescription", "lab_report", "other"],
            "description": "The classified type of the medical document."
        },
        "prescribing_doctor": {
            "type": "string",
            "description": "Name of the doctor who wrote or signed the document (letterhead, signature, stamp), in English, e.g. 'Dr. R. Mehta'. Omit if not visible."
        },
        "hospital_name": {
            "type": "string",
            "description": "Name of the hospital or clinic on the letterhead or stamp, in English, e.g. 'City Clinic'. Omit if not visible."
        },
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "record_type": {
                        "type": "string",
                        "enum": ["medication", "allergy", "diagnosis", "consultation", "lab_result", "hospitalization"]
                    },
                    "title": {
                        "type": "string",
                        "description": "A short, readable title, e.g., 'Amoxicillin 500mg' or 'Allergy to Penicillin' or 'X-ray of Chest'"
                    },
                    "details": {
                        "type": "object",
                        "description": "A JSON object with specific fields depending on the record type.",
                        "properties": {
                            "medicine": {"type": "string", "description": "Name of the medication"},
                            "dose": {"type": "string", "description": "Dosage amount, e.g., '500mg'"},
                            "timing": {"type": "string", "description": "When to take, e.g., 'Morning, Night' or '1-0-1'"},
                            "duration": {"type": "string", "description": "How long to take it, exactly as written, e.g. 'x 10 days', '1 week', '2/52'. Omit if not written."},
                            "intake_status": {"type": "string", "description": "e.g., 'Before food', 'After food'"},
                            "doctor_name": {"type": "string", "description": "Name of the prescribing physician if found"},
                            "text": {"type": "string", "description": "General text content for non-medication records"},
                            "notes": {"type": "string", "description": "Additional notes"},
                            "follow_up": {"type": "string", "description": "Follow-up instructions"},
                            "modality": {
                                "type": "string",
                                "enum": ["xray", "ct", "mri", "ultrasound", "other"],
                                "description": "Imaging only: the imaging modality."
                            },
                            "body_part": {
                                "type": "string",
                                "enum": BODY_PART_CODES,
                                "description": "Imaging only: the anatomical region shown in the image. Use 'unknown' if you cannot tell."
                            },
                            "laterality": {
                                "type": "string",
                                "enum": ["left", "right", "bilateral", "not_applicable", "unknown"],
                                "description": "Imaging only: which side, from L/R markers or anatomy."
                            },
                            "view": {"type": "string", "description": "Imaging only: projection, e.g. 'PA', 'AP', 'lateral', 'oblique'."}
                        }
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Your confidence in this extraction, 0.0 to 1.0.  Use 0.9-1.0 for clearly legible, unambiguous fields.  Use 0.5-0.8 for partially legible, inferred, or ambiguous data.  Use below 0.5 if the field was largely guessed."
                    },
                    "record_date": {
                        "type": "string",
                        "description": "The consultation/report date written on the document, in YYYY-MM-DD. Handwritten dates are DAY/MONTH/YEAR (21/8/25 = 2025-08-21). Omit if no date is written."
                    }
                },
                "required": ["record_type", "title", "details", "confidence"]
            }
        }
    },
    "required": ["document_type", "records"]
}

def extract_medical_records(file_bytes: bytes, mime_type: str, fallback_date: date, provided_doc_type: str = "prescription") -> Tuple[str, List[Dict[str, Any]]]:
    prompt = f"""
    You are an expert medical data extractor. I am providing a medical document.
    The user has indicated this document is a: '{provided_doc_type}'.
    
    Your task is to:
    1. Determine the overall document type (prescription or lab_report; medical images such as X-rays count as lab_report).
    2. Extract ALL medical records from this document with maximum accuracy.
    3. Assign a confidence score (0.0–1.0) to EACH extracted record.
    
    CONFIDENCE SCORING RULES:
    - 0.9–1.0: Field was clearly legible, unambiguous, and complete.
    - 0.7–0.89: Field was mostly legible but some parts were inferred from context.
    - 0.5–0.69: Field was partially illegible, ambiguous, or required significant inference.
    - Below 0.5: Field was largely guessed or barely readable.
    - If a medication record is missing the 'medicine' or 'dose' field, confidence MUST be ≤ 0.6.
    
    CRITICAL RULES FOR PRESCRIPTIONS:
    - You MUST extract EVERY single medication listed in the prescription. Do not skip any.
    - Each medicine must be a separate record with record_type = "medication".
    - For EACH medication, you MUST extract these fields in the details object:
      * 'medicine': The full medicine name exactly as written (e.g., "Paracetamol", "Amoxicillin 500mg")
      * 'dose': The dosage amount (e.g., "500mg", "10ml", "1 tablet")
      * 'timing': When to take the medicine (e.g., "Morning, Night", "1-0-1", "Three times a day")
      * 'intake_status': Whether to take before or after food (e.g., "Before food", "After food")
      * 'duration': How long to take it, if written (e.g., "x 10 days", "for 1 week", "2/52"). Keep it out of 'timing'.
    - Find the prescribing doctor: check the letterhead, the signature and the text under it, the rubber stamp,
      the footer, and for online consultations the doctor's details block (name, registration number). Return it
      as prescribing_doctor and also as 'doctor_name' in the details of EACH record. Transliterate non-English
      names into English. Only return a name you can actually read -- never guess.
    - Find the hospital / clinic the same way (letterhead, stamp, footer, or the online-consultation platform or
      clinic named on the slip) and return it as hospital_name.
    - Also extract any diagnoses, conditions, or health problems mentioned or strongly implied by the medications. Each diagnosis must be a separate record with record_type = "diagnosis".
    
    CRITICAL RULES FOR LAB REPORTS:
    - For lab results (X-rays, MRIs, CT scans, blood tests, ultrasounds, pathology), use record_type = "lab_result".
    - Make the title highly specific: e.g., "X-ray of Chest", "Complete Blood Count", "MRI of Brain".
    - Include findings, values, and reference ranges in the details 'text' field.
    
    CRITICAL RULES FOR MEDICAL IMAGES (X-ray, CT, MRI, ultrasound — the image itself, not a written report):
    - Return exactly ONE record with record_type = "lab_result" for the image.
    - Identify the anatomical region from the anatomy you can SEE, and set details.body_part to one of:
      chest, shoulder, skull_head, spine_cervical, spine_thoracic, spine_lumbar, abdomen_pelvis,
      arm, elbow, forearm, wrist, hand, hip, thigh, knee, leg, ankle, foot, other, unknown.
      Distinguish carefully: a shoulder view centres on the glenohumeral joint/humeral head with only part of
      the lung field; a chest view shows both lung fields, heart shadow and the full rib cage.
      Use 'unknown' rather than guessing.
    - Set details.modality, details.laterality (from L/R markers or anatomy) and details.view (PA, AP, lateral…).
    - details.text: ONE short neutral sentence naming the study and the anatomy shown, e.g.
      "Chest radiograph (X-ray) showing lungs, heart shadow, mediastinum, and thoracic cage."
      Do NOT diagnose from the image.
    - confidence reflects how sure you are of the BODY PART: 0.95+ only when the region is unmistakable.
    
    ACCURACY RULES:
    - Read the document VERY carefully. Extract every single item.
    - Do NOT hallucinate or invent medications or diagnoses that are not in the document.
    - Do NOT skip any medication even if it is partially legible — extract what you can read.
    DATE RULES:
    - record_date is the consultation / report date WRITTEN ON THE DOCUMENT, output as YYYY-MM-DD.
    - Dates on these documents are DAY/MONTH/YEAR (Indian format), never month/day:
      "12/10/22" = 2022-10-12, "21/8/25" = 2025-08-21, "5-3-2024" = 2024-03-05.
    - Every record from the same document gets the same consultation date.
    - If no date is written on the document, OMIT record_date. Never use today's date or guess.
    - IMPORTANT MULTILINGUAL RULE: If the text is in a non-English language, translate the extracted data into standard English. All JSON values must be in English.
    
    """
    
    # Retries / model fallback live in generate_content(); if every model
    # fails this raises and documents.py drops to local OCR.
    response = generate_content(
        [types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt],
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=extraction_schema,
            temperature=0.1,
        ),
        purpose="Extraction",
    )

    try:
        result = json.loads(response.text)
    except json.JSONDecodeError:
        return "other", []
        
    doc_type = result.get("document_type", "other")
    raw_records = result.get("records", [])
    prescribing_doctor = (result.get("prescribing_doctor") or "").strip()
    hospital_name = (result.get("hospital_name") or "").strip()
    
    processed_records = []
    for r in raw_records:
        r_date_str = r.get("record_date")

        # Use the date written on the document; if there isn't one (or it's
        # unparseable / in the future) fall back to the upload day and flag
        # it so the UI shows "Date not on document" instead of a fake date.
        r_date = None
        if r_date_str:
            try:
                r_date = date.fromisoformat(r_date_str)
            except ValueError:
                r_date = None
        if r_date is not None and r_date > date.today():
            r_date = None
        date_missing = r_date is None
        if date_missing:
            r_date = fallback_date

        r["record_date"] = r_date

        # ensure details is a dict
        if not isinstance(r.get("details"), dict):
            r["details"] = {"text": str(r.get("details", ""))}
        details = r["details"]
        # The model occasionally loops and returns a runaway string; keep
        # every text field to a sane length.
        for k, v in list(details.items()):
            if isinstance(v, str) and len(v) > MAX_FIELD_CHARS:
                details[k] = v[:MAX_FIELD_CHARS].rstrip() + "…"

        # Duration: take it from timing/notes if the model left it there
        # ("1-0-1 for 5 days", "x 10 days"); day counts are derived on read.
        if r.get("record_type") == "medication" and not details.get("duration"):
            for key in ("timing", "notes"):
                parsed = parse_duration(str(details.get(key) or ""))
                if parsed:
                    details["duration"] = format_duration(*parsed)
                    break

        # The model's self-rating, adjusted by checks we can verify (fields
        # present, dose has a unit, date written on the document) -- see
        # app/confidence.py. Missing medicine/dose still caps at 0.6 (FR-2.3).
        conf, basis = score_confidence(
            r.get("record_type"), r.get("title", ""), details, r.get("confidence"),
            "AI reading", not date_missing,
        )
        details["confidence_basis"] = basis
        # one doctor per document: copy it onto every record (used to link
        # this prescription to that doctor's consultation notes)
        if prescribing_doctor and not details.get("doctor_name"):
            details["doctor_name"] = prescribing_doctor
        if hospital_name and not details.get("hospital_name"):
            details["hospital_name"] = hospital_name
        if date_missing:
            details["is_fallback_date"] = True

        # Imaging: normalise the body part to our vocabulary and build the
        # title from it, so "X-ray of Chest" always matches details.body_part.
        # Only a real image counts: an imaging modality or an identified body
        # part. Blood tests etc. can come back with modality "other" -- those
        # stay ordinary lab results.
        is_imaging = (
            details.get("modality") in ("xray", "ct", "mri", "ultrasound")
            or normalize_body_part(details.get("body_part")) not in ("unknown", "other")
        )
        if r.get("record_type") == "lab_result" and not is_imaging:
            for k in ("modality", "body_part", "laterality", "view"):
                details.pop(k, None)
        if r.get("record_type") == "lab_result" and is_imaging:
            # For images the score is how sure the model is of the body part.
            conf = details.pop("confidence_basis")["base"]
            part = normalize_body_part(details.get("body_part"))
            if part == "unknown":
                conf = 0.0  # patient must pick the body part before verifying
            laterality = details.get("laterality") if details.get("laterality") in ("left", "right", "bilateral") else ""
            modality = details.get("modality") if details.get("modality") in MODALITIES else "xray"
            details.update({
                "body_part": part,
                "body_part_label": BODY_PARTS[part],
                "body_part_source": "ai",
                "modality": modality,
            })
            if laterality:
                details["laterality"] = laterality
            else:
                details.pop("laterality", None)
            view = normalize_view(details.get("view"))
            if view:
                details["view"] = view
            else:
                details.pop("view", None)
            if is_placeholder_text(details.get("text")) or len(details["text"]) > 400:
                # missing or runaway: describe it in the same style
                details["text"] = describe_image(modality, part, view)
            r["title"] = imaging_title(modality, part, laterality)

        r["confidence"] = conf
            
        processed_records.append(r)
        
    return doc_type, processed_records


# Used when Gemini is unavailable (quota, outage) so the consent screen still
# shows a sensible minimum-necessary suggestion instead of an error.
_RULE_BASED_SCOPES = [
    (("general", "family", "internal medicine", "physician", "practitioner"), ["full_history"]),
    (("cardio",), ["medications", "diagnoses", "labs"]),
    (("endocrin", "diabet"), ["medications", "diagnoses", "labs"]),
    (("nephro", "hepat", "gastro", "oncolog", "hematolog"), ["medications", "diagnoses", "labs"]),
    (("dermat", "allerg", "immunolog"), ["medications", "allergies", "diagnoses"]),
    (("anesth", "surgeon", "surgery"), ["medications", "allergies", "diagnoses", "labs"]),
    (("dent", "ophthal", "otolaryng", "ent specialist", "psychiat"), ["medications", "allergies"]),
]


def _rule_based_scope(specialty: str, reason: str) -> dict:
    lower = specialty.lower()
    scopes = next(
        (s for keys, s in _RULE_BASED_SCOPES if any(k in lower for k in keys)),
        ["medications", "allergies", "diagnoses"],
    )
    return {
        "recommended_scopes": scopes,
        "explanation": f"Standard minimum-necessary set for a {specialty} ({reason}).",
    }


def recommend_sharing_scope(specialty: str) -> dict:
    prompt = f"""
    You are a medical privacy and data-sharing AI. 
    A doctor with the specialty '{specialty}' has requested access to a patient's medical records.
    
    Which of the following data scopes are clinically necessary and appropriate for this specialty to see?
    Available scopes: ["medications", "labs", "allergies", "diagnoses", "full_history"]
    
    Consider the minimum necessary standard for data sharing. For example, a Cardiologist needs 'medications', 'diagnoses', and 'labs'. A General Practitioner might need 'full_history'.
    
    Output a valid JSON object exactly like this:
    {{
      "recommended_scopes": ["scope1", "scope2"],
      "explanation": "A short, 1-sentence explanation of why these scopes are recommended for this specialty."
    }}
    """
    
    try:
        response = generate_content(prompt, purpose="Scope recommendation")
    except Exception as e:
        print(f"Scope recommendation: Gemini unavailable ({str(e)[:80]}), using rule-based fallback")
        return _rule_based_scope(specialty, "AI assistant unavailable, rule-based suggestion")

    raw = response.text.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    
    try:
        return json.loads(raw)
    except Exception:
        return _rule_based_scope(specialty, "AI response could not be parsed, rule-based suggestion")


# Schema for structuring voice transcripts
voice_structure_schema = {
    "type": "object",
    "properties": {
        "record_type": {
            "type": "string",
            "enum": ["consultation", "diagnosis", "medication", "lab_result", "hospitalization", "allergy"],
            "description": "The type of medical record described in the dictation."
        },
        "title": {
            "type": "string",
            "description": "A short, readable title summarizing the dictation, e.g., 'Follow-up for Hypertension' or 'Prescribed Amoxicillin 500mg'"
        },
        "record_date": {
            "type": "string",
            "description": "The date mentioned in the dictation in YYYY-MM-DD format. If no date is mentioned, return the current date provided."
        },
        "details": {
            "type": "object",
            "properties": {
                "medicine": {"type": "string", "description": "Medicine name if a medication is being prescribed"},
                "dose": {"type": "string", "description": "Dosage if a medication is being prescribed, e.g. '500mg'"},
                "notes": {"type": "string", "description": "Clinical notes, consultation summary, or any additional context"},
                "text": {"type": "string", "description": "General text content for diagnoses, lab results, or allergies"},
                "follow_up": {"type": "string", "description": "Follow-up actions or next steps if mentioned"}
            }
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Any warnings about unclear audio segments, ambiguous medical terms, or content that the doctor should double-check."
        }
    },
    "required": ["record_type", "title", "record_date", "details"]
}


# ---- Rule-based structuring, used when every Gemini model is unavailable ----
_VOICE_TYPE_RULES = [
    ("allergy", r"\ballerg"),
    ("medication", r"\b(prescrib\w*|tab(let)?s?\.?|capsules?|syrup|injection|\d+\s?(mg|ml|mcg)|"
                   r"once daily|twice daily|thrice|bd|tds|od|at night|after food|before food)\b"),
    ("lab_result", r"\b(test|report|x-?ray|scan|mri|ct|ultrasound|blood (sugar|count|test)|hba1c|lab)\b"),
    ("hospitalization", r"\b(admit\w*|admission|hospitali[sz]\w*|discharg\w*)\b"),
    ("diagnosis", r"\b(diagnos\w*|known case|history of|suffer\w* from|has|have|condition|disease|disorder|"
                  r"infection|syndrome|hiv|aids|diabetes|hypertension|asthma|tb|tuberculosis|covid|cancer)\b"),
]
_FILLER = re.compile(
    r"^\s*(please\s+)?(add|note|record|write)?\s*(that\s+)?(to\s+)?(the\s+)?"
    r"(patient'?s?\s+(record|file|notes?)?|patient)?\s*(that\s+)?[,:-]?\s*",
    re.IGNORECASE,
)


def _structure_transcript_locally(transcript: str, current_date: str) -> dict:
    """Best-effort structure without AI: record type from keywords, medicine
    and dose from patterns, a cleaned-up title. The doctor reviews it."""
    text = " ".join(transcript.split())
    lower = text.lower()
    record_type = next((t for t, pat in _VOICE_TYPE_RULES if re.search(pat, lower)), "consultation")

    details = {"notes": text}
    med = re.search(r"([A-Za-z][A-Za-z\-]{2,})\s+(\d+(?:\.\d+)?\s?(?:mg|ml|mcg))\b", text, re.IGNORECASE)
    if med:
        details["medicine"], details["dose"] = med.group(1).capitalize(), med.group(2)
    follow = re.search(r"\b(follow[- ]?up|review|come back|revisit)\b[^.]*", text, re.IGNORECASE)
    if follow:
        details["follow_up"] = follow.group(0).strip()
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)

    core = _FILLER.sub("", text, count=1).strip() or text
    core = core[0].upper() + core[1:]
    allergen = re.search(r"allerg\w*\s+(?:to\s+)?([A-Za-z][\w\s-]{1,40}?)(?:[.,;]|$)", text, re.IGNORECASE)
    if record_type == "medication" and med:
        title = f"Prescribed {details['medicine']} {details['dose']}"
    elif record_type == "allergy" and allergen:
        title = f"Allergy to {allergen.group(1).strip()}"
    else:
        title = core if len(core) <= 60 else core[:57].rsplit(" ", 1)[0] + "…"

    return {
        "record_type": record_type,
        "title": title,
        "record_date": date_match.group(1) if date_match else current_date,
        "details": details,
        "warnings": [
            "AI structuring isn't available right now (Gemini is busy or out of quota), so these fields were "
            "filled in with basic rules. Please check the type, title and wording before saving."
        ],
        "structured_by": "rules",
    }


def structure_voice_transcript(transcript: str, current_date: str) -> dict:
    """
    Takes a raw voice transcript from a doctor's dictation and uses Gemini
    to structure it into the fields needed for a consultation record.
    """
    prompt = f"""
    You are an expert medical documentation assistant. A doctor has dictated the following
    clinical note using voice input. Your job is to structure this dictation into a
    well-organized medical record.

    DOCTOR'S DICTATION:
    "{transcript}"

    INSTRUCTIONS:
    1. Determine the record_type from the content:
       - If the doctor is prescribing medication → "medication"
       - If describing a diagnosis or condition → "diagnosis"
       - If describing a general consultation or visit → "consultation"
       - If reporting lab/test results → "lab_result"
       - If describing a hospitalization → "hospitalization"
       - If noting an allergy → "allergy"
    2. Create a concise, professional title summarizing the record.
    3. Extract the date if mentioned. If no date is mentioned, use: {current_date}
    4. Structure the details:
       - For medications: extract 'medicine' and 'dose' fields
       - For all types: include 'notes' with the full clinical context
       - If follow-up actions are mentioned, include them in 'follow_up'
    5. MEDICAL TERMINOLOGY: Correctly recognize and spell medical terms, drug names,
       anatomical references, and clinical abbreviations (e.g., "BP" → blood pressure,
       "tid" → three times daily, "PRN" → as needed).
    6. WARNINGS: If any part of the dictation is ambiguous, unclear, or could be
       misinterpreted, add a warning so the doctor can double-check it.
    """

    try:
        response = generate_content(
            prompt,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=voice_structure_schema,
                temperature=0.1
            )
        )
        result = json.loads(response.text)
        return result
    except Exception as e:
        print(f"Voice structuring: Gemini unavailable ({_short_error(e)}), using rule-based fallback")
        return _structure_transcript_locally(transcript, current_date)

