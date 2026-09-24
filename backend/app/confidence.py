"""
Confidence score for an extracted record.

The model's own rating (or, on the local-OCR path, Tesseract's legibility
score) is only half the story: it rates how well it *read* the page, not
whether the record came out complete. So the stored confidence is

    confidence = base × (0.5 + 0.5 × checks_passed / checks_total)

where the checks are things we can verify in code:
  - medication: medicine named, dose has a number and unit, timing given
  - diagnosis / allergy: a meaningful title
  - lab result / consultation / hospitalization: a meaningful title and some text
  - every record: a date was written on the document

A complete record keeps the base score (0.95 stays 95%); each failed check
lowers it, and a record failing everything drops to half the base. A
medication without medicine or dose is still capped at 0.6 (FR-2.3), and
anything under 0.7 is flagged "Low confidence" during verification.

The inputs are stored in details.confidence_basis so the UI can explain
the number.
"""
import re
from typing import Optional, Tuple

DEFAULT_BASE = 0.7  # the model didn't rate itself: treat as "check it"
_DOSE = re.compile(r"\d+(\.\d+)?\s*(mg|mcg|µg|g|gm|ml|iu|units?|%|tabs?|tablets?|caps?|drops?|puffs?|sachets?)\b", re.I)
_LETTERS = re.compile(r"[A-Za-z]")


def _meaningful(text: Optional[str], min_letters: int = 3) -> bool:
    return bool(text) and len(_LETTERS.findall(str(text))) >= min_letters


def score(record_type: str, title: str, details: dict, base: Optional[float],
          base_source: str, date_on_document: bool) -> Tuple[float, dict]:
    try:
        base = DEFAULT_BASE if base is None else max(0.0, min(1.0, float(base)))
    except (TypeError, ValueError):
        base = DEFAULT_BASE

    checks = {}
    if record_type == "medication":
        checks["medicine named"] = _meaningful(details.get("medicine"), 2)
        checks["dose with unit"] = bool(_DOSE.search(str(details.get("dose") or "")))
        checks["timing given"] = bool(str(details.get("timing") or details.get("frequency") or "").strip())
    else:
        checks["clear title"] = _meaningful(title)
        if record_type not in ("diagnosis", "allergy"):  # for these the title is the content
            checks["details present"] = any(_meaningful(details.get(k), 4) for k in ("text", "notes"))
    checks["date on document"] = date_on_document

    passed = sum(checks.values())
    conf = base * (0.5 + 0.5 * passed / len(checks))
    if record_type == "medication" and not (details.get("medicine") and details.get("dose")):
        conf = min(conf, 0.6)
    conf = round(conf, 3)
    basis = {
        "base": round(base, 3),
        "base_source": base_source,
        "checks_passed": passed,
        "checks_total": len(checks),
        "missing": [name for name, ok in checks.items() if not ok],
    }
    return conf, basis
