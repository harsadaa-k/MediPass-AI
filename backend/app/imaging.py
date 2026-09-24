"""
Radiology image handling: anatomical-region vocabulary, DICOM decoding, and
reconciling the body part from its possible sources.

Where the body part comes from, strongest first:
  1. DICOM metadata (BodyPartExamined, falling back to StudyDescription) --
     deterministic, but real-world PACS tags are sometimes wrong/blank.
  2. Gemini vision (llm.extract_medical_records) -- reads the image itself.
  3. Burned-in text found by local OCR ("CHEST PA", "L KNEE") -- weak hint.
  4. Nothing -> "unknown".

No automatic classifier is 100% accurate, so every imaging record is saved
*unverified* and the patient must confirm (or pick) the body part in the
verify queue before it reaches the timeline. records.py refuses to verify an
imaging record whose body part is still "unknown". The stored value is
therefore always human-confirmed; `body_part_source` records how it was
suggested.
"""
import io
import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- vocabulary

# code -> human label. Order is the order shown in the verify dropdown.
BODY_PARTS: Dict[str, str] = {
    "chest": "Chest",
    "shoulder": "Shoulder",
    "skull_head": "Skull / head",
    "spine_cervical": "Cervical spine",
    "spine_thoracic": "Thoracic spine",
    "spine_lumbar": "Lumbar spine",
    "abdomen_pelvis": "Abdomen / pelvis",
    "arm": "Arm (humerus)",
    "elbow": "Elbow",
    "forearm": "Forearm",
    "wrist": "Wrist",
    "hand": "Hand",
    "hip": "Hip",
    "thigh": "Thigh (femur)",
    "knee": "Knee",
    "leg": "Leg (tibia / fibula)",
    "ankle": "Ankle",
    "foot": "Foot",
    "other": "Other",
    "unknown": "Not identified",
}
BODY_PART_CODES = list(BODY_PARTS)

MODALITIES = {"xray": "X-ray", "ct": "CT", "mri": "MRI", "ultrasound": "Ultrasound", "other": "Imaging"}

# DICOM BodyPartExamined defined terms (PS3.16 Annex L) and common variants.
_DICOM_BODY_PART = {
    "CHEST": "chest", "THORAX": "chest", "LUNG": "chest", "RIB": "chest", "RIBS": "chest",
    "SHOULDER": "shoulder", "CLAVICLE": "shoulder", "SCAPULA": "shoulder",
    "SKULL": "skull_head", "HEAD": "skull_head", "BRAIN": "skull_head", "FACE": "skull_head",
    "SINUS": "skull_head", "JAW": "skull_head", "TMJ": "skull_head",
    "CSPINE": "spine_cervical", "NECK": "spine_cervical",
    "TSPINE": "spine_thoracic",
    "LSPINE": "spine_lumbar", "LSSPINE": "spine_lumbar", "SSPINE": "spine_lumbar", "SACRUM": "spine_lumbar",
    "ABDOMEN": "abdomen_pelvis", "PELVIS": "abdomen_pelvis", "ABDOMENPELVIS": "abdomen_pelvis", "KUB": "abdomen_pelvis",
    "HUMERUS": "arm", "ARM": "arm", "UPRARM": "arm",
    "ELBOW": "elbow",
    "FOREARM": "forearm", "RADIUS": "forearm", "ULNA": "forearm",
    "WRIST": "wrist",
    "HAND": "hand", "FINGER": "hand", "THUMB": "hand",
    "HIP": "hip",
    "FEMUR": "thigh", "THIGH": "thigh", "UPRLEG": "thigh",
    "KNEE": "knee", "PATELLA": "knee",
    "LEG": "leg", "LOWLEG": "leg", "TIBIA": "leg", "FIBULA": "leg",
    "ANKLE": "ankle",
    "FOOT": "foot", "TOE": "foot", "CALCANEUS": "foot", "HEEL": "foot",
}

# Words that might appear burned into an image or in a study description.
_TEXT_HINTS: List[Tuple[str, str]] = [
    (r"\bc[\s\-]?spine\b|\bcervical\b", "spine_cervical"),
    (r"\bt[\s\-]?spine\b|\bthoracic spine\b|\bdorsal spine\b", "spine_thoracic"),
    (r"\bl[\s\-]?spine\b|\blumbar\b|\blumbosacral\b", "spine_lumbar"),
    (r"\bchest\b|\bthorax\b|\bcxr\b|\blungs?\b", "chest"),
    (r"\bshoulder\b|\bclavicle\b|\bscapula\b", "shoulder"),
    (r"\bskull\b|\bhead\b|\bsinus(es)?\b|\bmandible\b", "skull_head"),
    (r"\babdomen\b|\bpelvis\b|\bkub\b", "abdomen_pelvis"),
    (r"\bhumerus\b", "arm"),
    (r"\belbow\b", "elbow"),
    (r"\bforearm\b|\bradius\b|\bulna\b", "forearm"),
    (r"\bwrist\b", "wrist"),
    (r"\bhand\b|\bfingers?\b", "hand"),
    (r"\bhip\b", "hip"),
    (r"\bfemur\b|\bthigh\b", "thigh"),
    (r"\bknee\b|\bpatella\b", "knee"),
    (r"\btibia\b|\bfibula\b|\btib[\s/]*fib\b", "leg"),
    (r"\bankle\b", "ankle"),
    (r"\bfoot\b|\bfeet\b|\btoes?\b|\bcalcaneus\b", "foot"),
]


def normalize_body_part(value: Optional[str]) -> str:
    """Map any label/code/DICOM term to one of BODY_PART_CODES."""
    if not value:
        return "unknown"
    v = str(value).strip()
    if v.lower() in BODY_PARTS:
        return v.lower()
    key = re.sub(r"[^A-Z]", "", v.upper())
    if key in _DICOM_BODY_PART:
        return _DICOM_BODY_PART[key]
    hint = body_part_from_text(v)
    return hint or "unknown"


def body_part_from_text(text: str) -> Optional[str]:
    lower = (text or "").lower()
    for pattern, code in _TEXT_HINTS:
        if re.search(pattern, lower):
            return code
    return None


# What a normal study of each region shows -- used to describe an image the
# way the AI does ("Chest radiograph (X-ray) showing lungs, heart shadow,
# mediastinum and thoracic cage.") when it returned no usable description.
_STRUCTURES = {
    "chest": "lungs, heart shadow, mediastinum and thoracic cage",
    "shoulder": "humeral head, glenoid, clavicle and scapula",
    "skull_head": "skull vault and facial bones",
    "spine_cervical": "cervical vertebrae and disc spaces",
    "spine_thoracic": "thoracic vertebrae and disc spaces",
    "spine_lumbar": "lumbar vertebrae and disc spaces",
    "abdomen_pelvis": "abdomen, bowel gas pattern and pelvic bones",
    "arm": "humerus with the shoulder and elbow ends",
    "elbow": "distal humerus, radial head and olecranon at the elbow joint",
    "forearm": "radius and ulna",
    "wrist": "distal radius and ulna and the carpal bones",
    "hand": "metacarpals and phalanges",
    "hip": "femoral head, neck and acetabulum",
    "thigh": "femur",
    "knee": "distal femur, proximal tibia and fibula and patella",
    "leg": "tibia and fibula",
    "ankle": "distal tibia and fibula and talus",
    "foot": "tarsal and metatarsal bones and phalanges",
}
_STUDY = {"xray": "radiograph (X-ray)", "ct": "CT scan", "mri": "MRI scan", "ultrasound": "ultrasound", "other": "image"}


def is_placeholder_text(text: Optional[str]) -> bool:
    """The stand-in text used when there was no description ("X-ray image uploaded.")."""
    return not text or bool(re.fullmatch(r"\s*(X-ray|CT|MRI|Ultrasound|Imaging|DICOM) image uploaded\.?\s*", text, re.I))


def describe_image(modality: str, body_part: str, view: str = "") -> str:
    """Neutral one-line description of an imaging study, no findings."""
    study = _STUDY.get(modality, "image")
    if view:
        study = study.replace(")", f", {view} view)") if study.endswith(")") else f"{study} ({view} view)"
    region = BODY_PARTS.get(body_part, "").split(" (")[0].split(" /")[0]  # "Arm (humerus)" -> "Arm"
    if body_part in _STRUCTURES:
        return f"{region} {study} showing the {_STRUCTURES[body_part]}."
    if body_part in BODY_PARTS and body_part not in ("unknown", "other"):
        return f"{region} {study}."
    return f"{MODALITIES.get(modality, 'Imaging')} image uploaded."


_VIEWS = [  # (pattern, label) -- most specific first
    (r"\bap\s*supine\b", "AP supine"), (r"\bpa\b|postero-?anterior", "PA"), (r"\bap\b|antero-?posterior", "AP"),
    (r"\blat(eral)?\b", "lateral"), (r"\boblique\b", "oblique"), (r"\blordotic\b", "lordotic"),
    (r"\bdecubitus\b", "decubitus"), (r"\baxial\b", "axial"), (r"\bsagittal\b", "sagittal"),
    (r"\bcoronal\b", "coronal"), (r"\bfrontal\b", "frontal"),
]


def normalize_view(value: Optional[str]) -> str:
    """
    The projection as a short label ("PA", "AP / lateral"), or "" if it
    can't be told. The model sometimes returns a runaway sentence here
    ("PA_or_AP_unknown_exact_projection_but_full_chest_visible..."); only
    known projection names are kept, and an unsure answer ("PA or AP") is
    dropped rather than shown.
    """
    if not value:
        return ""
    text = str(value)[:200].replace("_", " ").lower()
    if re.search(r"\b(or|unknown|unclear|likely|probably)\b", text):
        return ""
    found = []
    for pattern, label in _VIEWS:
        if re.search(pattern, text) and label not in found and not (label == "AP" and "AP supine" in found):
            found.append(label)
    return " / ".join(found[:2])


def imaging_title(modality: str, body_part: str, laterality: str = "") -> str:
    mod = MODALITIES.get(modality, "X-ray")
    if body_part in ("unknown", ""):
        return f"{mod} (body part not identified)"
    side = f"{laterality.capitalize()} " if laterality in ("left", "right") else ""
    part = BODY_PARTS.get(body_part, body_part)
    return f"{mod} of {side}{part[0].lower() + part[1:] if side else part}"


# ---------------------------------------------------------------- DICOM

def is_dicom(content: bytes, content_type: str = "", file_name: str = "") -> bool:
    if content_type in ("application/dicom", "application/dicom+json"):
        return True
    if len(content) > 132 and content[128:132] == b"DICM":
        return True
    return file_name.lower().endswith((".dcm", ".dicom"))


def read_dicom(content: bytes) -> Tuple[Optional[bytes], Dict[str, str]]:
    """
    Returns (png_bytes or None, metadata). png_bytes is None when the pixel
    data uses a compression codec that isn't installed (e.g. JPEG 2000) --
    the metadata is still usable in that case.
    """
    import pydicom
    from PIL import Image

    ds = pydicom.dcmread(io.BytesIO(content), force=True)

    def tag(name):
        val = getattr(ds, name, "")
        return str(val).strip() if val is not None else ""

    meta = {
        "body_part_examined": tag("BodyPartExamined"),
        "study_description": tag("StudyDescription"),
        "series_description": tag("SeriesDescription"),
        "modality": tag("Modality"),
        "view_position": tag("ViewPosition"),
        "laterality": tag("ImageLaterality") or tag("Laterality"),
        "study_date": tag("StudyDate"),
    }

    png = None
    try:
        import numpy as np
        from pydicom.pixels import apply_voi_lut

        arr = ds.pixel_array
        if arr.ndim == 3 and arr.shape[-1] not in (3, 4):
            arr = arr[arr.shape[0] // 2]  # multi-frame: middle frame
        try:
            arr = apply_voi_lut(arr, ds)  # apply the scanner's display window
        except Exception:
            pass
        arr = arr.astype("float32")
        lo, hi = np.percentile(arr, 0.5), np.percentile(arr, 99.5)
        if hi <= lo:
            lo, hi = float(arr.min()), float(arr.max()) or 1.0
        arr = np.clip((arr - lo) / (hi - lo), 0, 1) * 255
        if tag("PhotometricInterpretation") == "MONOCHROME1":
            arr = 255 - arr  # inverted greyscale
        img = Image.fromarray(arr.astype("uint8"))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
    except Exception as e:
        print(f"DICOM: could not decode pixel data ({str(e)[:80]}); using metadata only")

    return png, meta


def body_part_from_dicom(meta: Dict[str, str]) -> Optional[str]:
    code = normalize_body_part(meta.get("body_part_examined"))
    if code != "unknown":
        return code
    for field in ("study_description", "series_description"):
        hint = body_part_from_text(meta.get(field, ""))
        if hint:
            return hint
    return None


def dicom_modality(meta: Dict[str, str]) -> str:
    return {"CR": "xray", "DX": "xray", "RF": "xray", "MG": "xray", "CT": "ct", "MR": "mri", "US": "ultrasound"}.get(
        meta.get("modality", "").upper(), "xray"
    )


def dicom_laterality(meta: Dict[str, str]) -> str:
    return {"L": "left", "R": "right", "B": "bilateral"}.get(meta.get("laterality", "").upper()[:1], "")


# ---------------------------------------------------------------- reconcile

def reconcile(ai_part: Optional[str], ai_conf: float, dicom_part: Optional[str]) -> Tuple[str, float, str, Optional[str]]:
    """
    Combine the AI's reading of the image with the DICOM tag.
    Returns (body_part, confidence, source, conflict_note).
    """
    ai_part = normalize_body_part(ai_part) if ai_part else None
    if ai_part == "unknown":
        ai_part = None

    if dicom_part and ai_part:
        if dicom_part == ai_part:
            return dicom_part, max(ai_conf, 0.97), "dicom_metadata+ai", None
        note = (f"The file's DICOM tag says {BODY_PARTS[dicom_part]} but the image looks like "
                f"{BODY_PARTS[ai_part]}. Please choose the correct body part.")
        return ai_part, min(ai_conf, 0.5), "conflict", note
    if dicom_part:
        return dicom_part, 0.9, "dicom_metadata", None
    if ai_part:
        return ai_part, ai_conf, "ai", None
    return "unknown", 0.0, "none", None


def imaging_record(body_part: str, confidence: float, source: str, *, modality: str = "xray",
                   laterality: str = "", view: str = "", findings: str = "",
                   note: Optional[str] = None) -> Dict:
    """The record dict shape documents.py stores (minus record_date)."""
    details = {
        "body_part": body_part,
        "body_part_label": BODY_PARTS.get(body_part, body_part),
        "body_part_source": source,
        "modality": modality,
        "text": findings or describe_image(modality, body_part, view),
    }
    if laterality:
        details["laterality"] = laterality
    if view:
        details["view"] = view
    if note:
        details["body_part_note"] = note
    return {
        "record_type": "lab_result",
        "title": imaging_title(modality, body_part, laterality),
        "details": details,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
    }
