// Confidence of an extracted record: the AI's (or OCR's) own rating adjusted
// by field checks done in code (backend app/confidence.py).
export const LOW_CONFIDENCE = 0.7;

// "AI reading 95% · 3 of 4 checks passed · missing: timing given"
export function confidenceExplanation(record) {
  const b = record.details?.confidence_basis;
  if (!b) return 'How sure the extraction is about this record.';
  const parts = [
    `${b.base_source} ${Math.round(b.base * 100)}%`,
    `${b.checks_passed} of ${b.checks_total} checks passed`,
  ];
  if (b.missing?.length) parts.push(`missing: ${b.missing.join(', ')}`);
  return parts.join(' · ');
}
