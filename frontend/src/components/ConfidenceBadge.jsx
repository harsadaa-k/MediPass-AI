import { LOW_CONFIDENCE, confidenceExplanation } from '../confidence';

/** Confidence badge for an extracted record; hover to see the breakdown. */
export default function ConfidenceBadge({ record }) {
  if (record.confidence == null) return null;
  const low = record.confidence < LOW_CONFIDENCE;
  return (
    <span className={`badge ${low ? 'badge-amber' : 'badge-gray'} mono`} title={confidenceExplanation(record)}>
      {Math.round(record.confidence * 100)}% confidence
    </span>
  );
}
