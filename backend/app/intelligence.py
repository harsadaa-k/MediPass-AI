"""
Timeline intelligence: conflict detection.

Per REQUIREMENTS.md FR-4.3: this layer only *flags* things for a human to
look at. It never decides which conflicting record is correct.

(Gap detection -- "No record available between X and Y" -- was removed: it
only reflected which documents had been uploaded, not the patient's care.)

Conflict detection is rule-based (no LLM calls) so it can run on every
timeline view without consuming API quota.
"""
import json
import re
from typing import List, Dict, Any

# ---- Known drug-class / cross-allergy mappings for rule-based detection ----
# Maps an allergy keyword to a list of medication keywords that conflict.
_ALLERGY_DRUG_MAP = {
    "penicillin": ["amoxicillin", "ampicillin", "penicillin", "augmentin",
                   "piperacillin", "flucloxacillin", "dicloxacillin"],
    "sulfa": ["sulfamethoxazole", "trimethoprim", "bactrim", "sulfasalazine"],
    "aspirin": ["aspirin"],
    "nsaid": ["ibuprofen", "naproxen", "diclofenac", "aspirin", "celecoxib",
              "indomethacin", "piroxicam", "meloxicam"],
    "cephalosporin": ["cephalexin", "cefazolin", "ceftriaxone", "cefuroxime"],
}

# Known dangerous drug-drug interaction pairs (both directions checked)
_DRUG_INTERACTIONS = [
    ({"warfarin", "coumadin"}, {"aspirin"}, "Concurrent Warfarin and Aspirin significantly increases bleeding risk."),
    ({"warfarin", "coumadin"}, {"ibuprofen", "naproxen", "diclofenac"}, "NSAIDs with Warfarin greatly increases bleeding risk."),
    ({"methotrexate"}, {"trimethoprim", "bactrim", "sulfamethoxazole"}, "Trimethoprim/Sulfamethoxazole with Methotrexate can cause fatal bone marrow suppression."),
    ({"lithium"}, {"ibuprofen", "naproxen", "diclofenac", "celecoxib"}, "NSAIDs increase Lithium levels, risking toxicity."),
    ({"digoxin"}, {"amiodarone"}, "Amiodarone increases Digoxin levels, risking toxicity."),
]

# Phrases that indicate "no known allergies"
_NKDA_PATTERNS = re.compile(
    # \w* lets "allerg" match allergy/allergies/allergic before the closing \b
    r"\b(no\s+known\s+allerg\w*|nkda|nka|no\s+allerg\w*|no\s+drug\s+allerg\w*)\b",
    re.IGNORECASE,
)


def _parse_details(details) -> dict:
    """Safely parse details whether it's a JSON string or already a dict."""
    if isinstance(details, dict):
        return details
    if isinstance(details, str):
        try:
            return json.loads(details)
        except (json.JSONDecodeError, TypeError):
            return {"text": details}
    return {}


def _extract_text_from_record(record: Dict[str, Any]) -> str:
    """Get all searchable text from a record's details."""
    details = _parse_details(record.get("details", {}))
    parts = []
    for key in ("text", "medicine", "dose", "notes"):
        val = details.get(key, "")
        if val:
            parts.append(str(val))
    title = record.get("title", "")
    if title:
        parts.append(title)
    return " ".join(parts).lower()


def detect_conflicts(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rule-based conflict detection — runs entirely locally, no LLM calls.
    Detects:
      1. Allergy ↔ "no known allergies" contradictions
      2. Allergy ↔ prescribed medication cross-reactivity
      3. Known dangerous drug-drug interactions
    """
    if len(records) < 2:
        return []

    flags: List[Dict[str, Any]] = []

    # Categorize records
    allergy_records = []
    medication_records = []

    for r in records:
        rtype = r.get("record_type")
        # Handle both enum and string
        rtype_str = rtype.value if hasattr(rtype, "value") else str(rtype)
        text = _extract_text_from_record(r)

        if rtype_str == "allergy":
            allergy_records.append({"id": str(r["id"]), "text": text})
        if rtype_str == "medication":
            medication_records.append({"id": str(r["id"]), "text": text})

    # --- Check 1: "No known allergies" vs specific allergy ---
    nkda_records = [a for a in allergy_records if _NKDA_PATTERNS.search(a["text"])]
    specific_allergy_records = [a for a in allergy_records if not _NKDA_PATTERNS.search(a["text"])]

    for nkda in nkda_records:
        for specific in specific_allergy_records:
            flags.append({
                "type": "conflict",
                "message": (
                    f"One record states 'no known allergies' but another "
                    f"documents a specific allergy. Please reconcile."
                ),
                "record_ids": [nkda["id"], specific["id"]],
            })

    # --- Check 2: Allergy ↔ Medication cross-reactivity ---
    for allergy_rec in specific_allergy_records:
        allergy_text = allergy_rec["text"]
        for allergy_kw, drug_kws in _ALLERGY_DRUG_MAP.items():
            if allergy_kw in allergy_text:
                for med_rec in medication_records:
                    med_text = med_rec["text"]
                    for drug_kw in drug_kws:
                        if drug_kw in med_text:
                            flags.append({
                                "type": "conflict",
                                "message": (
                                    f"Patient has a documented {allergy_kw} allergy, "
                                    f"but {drug_kw} (a {allergy_kw}-class drug) appears "
                                    f"in their medication list. This is a potential "
                                    f"cross-allergy risk."
                                ),
                                "record_ids": [allergy_rec["id"], med_rec["id"]],
                            })
                            break  # one flag per allergy-med pair

    # --- Check 3: Drug-drug interactions ---
    for med_a in medication_records:
        for med_b in medication_records:
            if med_a["id"] >= med_b["id"]:
                continue  # avoid duplicates and self-comparison
            for group_a, group_b, reason in _DRUG_INTERACTIONS:
                a_match = any(kw in med_a["text"] for kw in group_a)
                b_match = any(kw in med_b["text"] for kw in group_b)
                # Check both directions
                a_match_rev = any(kw in med_a["text"] for kw in group_b)
                b_match_rev = any(kw in med_b["text"] for kw in group_a)
                if (a_match and b_match) or (a_match_rev and b_match_rev):
                    flags.append({
                        "type": "conflict",
                        "message": reason,
                        "record_ids": [med_a["id"], med_b["id"]],
                    })

    # Deduplicate by record_ids pair
    seen = set()
    unique_flags = []
    for f in flags:
        key = tuple(sorted(f["record_ids"]))
        if key not in seen:
            seen.add(key)
            unique_flags.append(f)

    return unique_flags
