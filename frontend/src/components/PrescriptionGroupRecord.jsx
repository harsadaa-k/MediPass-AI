import { useState } from 'react';
import ViewSourceButton from './ViewSourceButton';
import RecordDates from './RecordDates';
import CourseInfo from './CourseInfo';
import PrescriberEditor from './PrescriberEditor';

/**
 * A consolidated timeline box that groups related records together.
 * Used for both "Medicines" (medications) and "Diagnosis" (diagnoses).
 *
 * Props:
 *  - records: array of record objects sharing the same source_document_id
 *  - groupType: 'medicines' | 'diagnosis'
 */
export default function GroupedRecordBox({ records, groupType = 'medicines', anchorId, children, prescriber }) {
  const [expanded, setExpanded] = useState(false);

  if (!records || records.length === 0) return null;

  // Use the first record for shared metadata (date, source)
  const anchor = records[0];
  const sourceDocId = anchor.source_document_id;
  const count = records.length;

  const isMedicines = groupType === 'medicines';
  const boxTitle = isMedicines ? 'Medicines' : 'Diagnosis';
  const boxEmoji = isMedicines ? '💊' : '🩺';
  const itemLabel = isMedicines
    ? `${count} medication${count !== 1 ? 's' : ''}`
    : `${count} diagnosis${count !== 1 ? 'es' : ''}`;
  const toggleLabel = isMedicines ? 'medicines' : 'diagnoses';

  return (
    <div id={anchorId} className={`timeline-record prescription-group source-ai_extracted`}>
      <RecordDates record={anchor} />
      <div className="record-body">
        <div className="record-title-row">
          <span className="record-title">{boxTitle}</span>
          <span className="badge badge-teal">
            {boxEmoji} {itemLabel}
          </span>
        </div>

        {/* Who wrote the prescription: patients can fill it in / correct it */}
        {prescriber && isMedicines && (
          prescriber.canEdit ? (
            <PrescriberEditor
              documentId={sourceDocId}
              doctor={anchor.details?.doctor_name || ''}
              hospital={anchor.details?.hospital_name || ''}
              locked={prescriber.locked}
              onSaved={prescriber.onSaved}
            />
          ) : (anchor.details?.doctor_name || anchor.details?.hospital_name) ? (
            <div className="prescriber-line">
              <span>
                Prescribed by <strong>{anchor.details?.doctor_name || 'unknown doctor'}</strong>
                {anchor.details?.hospital_name ? <> · {anchor.details.hospital_name}</> : null}
              </span>
            </div>
          ) : null
        )}

        {/* Collapsed summary: show first few item names */}
        {!expanded && (
          <div className="record-detail" style={{ marginBottom: '0.3rem' }}>
            {records
              .slice(0, 3)
              .map((r) => {
                if (isMedicines) return r.details?.medicine || r.title;
                return r.details?.text || r.title;
              })
              .join(', ')}
            {count > 3 && `, +${count - 3} more`}
          </div>
        )}

        {/* Expanded: full list of items */}
        {expanded && isMedicines && (
          <div className="prescription-med-list">
            {records.map((r) => (
              <div key={r.id} className="prescription-med-item">
                <div className="med-item-name">{r.details?.medicine || r.title}</div>
                <div className="med-item-details">
                  {r.details?.dose && <span className="med-detail-chip">{r.details.dose}</span>}
                  {r.details?.timing && <span className="med-detail-chip">{r.details.timing}</span>}
                  {r.details?.intake_status && <span className="med-detail-chip">{r.details.intake_status}</span>}
                  {r.course?.ongoing && <CourseInfo course={r.course} />}
                </div>
                {r.course && !r.course.ongoing && (
                  <div className="med-item-course"><CourseInfo course={r.course} /></div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Diagnoses carry long clinical text: stack it as wrapping paragraphs
            inside the card instead of one-line chips that overflow it. */}
        {expanded && !isMedicines && (
          <div className="prescription-med-list">
            {records.map((r) => (
              <div key={r.id} className="diagnosis-item">
                <div className="med-item-name">{r.title}</div>
                {r.details?.text && <p className="diagnosis-text">{r.details.text}</p>}
                {r.details?.notes && <p className="diagnosis-text diagnosis-notes">{r.details.notes}</p>}
                {r.details?.follow_up && (
                  <p className="diagnosis-text"><strong>Follow-up:</strong> {r.details.follow_up}</p>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="record-source-row">
          <button
            className="prescription-toggle"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? '▲ Collapse' : `▼ View all ${toggleLabel}`}
          </button>
          <span className="record-source">Extracted from a document</span>
          {sourceDocId && <ViewSourceButton documentId={sourceDocId} />}
        </div>
        {children}
      </div>
    </div>
  );
}
