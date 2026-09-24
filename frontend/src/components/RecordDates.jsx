import { parseUtc } from '../grants';

/**
 * Date column for a timeline card. Shows both dates a record has:
 *  - the consultation / report date (from the document, or entered by the
 *    doctor) -- what the timeline is ordered by
 *  - when it was logged in MediPass
 * If the document had no date, the upload day was used and we say so.
 */
export default function RecordDates({ record }) {
  const noDateOnDocument = record.details?.is_fallback_date;
  const label = record.record_type === 'lab_result' ? 'Report date' : 'Consultation date';
  const logged = parseUtc(record.logged_at);

  return (
    <div className="record-date">
      <div className="mono">{record.record_date}</div>
      {noDateOnDocument ? (
        <span
          className="badge badge-amber"
          style={{ fontSize: '0.7rem' }}
          title="No date was written on the document, so the upload day is shown."
        >
          Date not on document
        </span>
      ) : (
        <div className="record-date-label">{label}</div>
      )}
      {logged && (
        <div className="record-date-label" title={logged.toLocaleString()}>
          Logged in MediPass {logged.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
        </div>
      )}
    </div>
  );
}
