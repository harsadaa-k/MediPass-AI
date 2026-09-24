import ViewSourceButton from './ViewSourceButton';
import RecordDates from './RecordDates';
import CourseInfo from './CourseInfo';
import ConfidenceBadge from './ConfidenceBadge';

const SOURCE_LABEL = {
  patient_provided: 'Added by you',
  ai_extracted: 'Extracted from a document',
  doctor_generated: 'Added by your doctor',
  hospital_generated: 'Added by hospital',
  lab_generated: 'Added by lab',
};

function detailsToText(details, hasCourse = false) {
  if (!details) return '';
  if (typeof details === 'string') return details;
  if (details.text) return details.text;
  if (details.medicine) {
    const parts = [details.medicine];
    if (details.dose) parts.push(`— ${details.dose}`);
    if (details.frequency) parts.push(`· ${details.frequency}`);
    if (details.duration && !hasCourse) parts.push(`· ${details.duration}`); // else shown as "Course"
    return parts.join(' ').trim();
  }
  if (details.notes) return details.notes;
  // fall back to a compact key: value rendering
  return Object.entries(details)
    .filter(([k, v]) => !['raw_line', 'is_fallback_date', 'confidence_basis'].includes(k) && typeof v !== 'object')
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
    .join(' · ');
}

export default function TimelineRecord({ record, children }) {
  return (
    <div id={record.id} className={`timeline-record source-${record.source_type}`}>
      <RecordDates record={record} />
      <div className="record-body">
        <div className="record-title-row">
          <span className="record-title">{record.title}</span>
          <ConfidenceBadge record={record} />
        </div>
        <div className="record-detail">{detailsToText(record.details, !!record.course)}</div>
        {record.course && (
          <div className="record-detail" style={{ fontSize: '0.82rem' }}>
            Course: <CourseInfo course={record.course} />
          </div>
        )}
        {record.details?.body_part_label && (
          <div className="record-detail muted" style={{ fontSize: '0.82rem' }}>
            Body part: <strong>{record.details.body_part_label}</strong>
            {record.details.laterality && record.details.laterality !== 'bilateral' ? ` (${record.details.laterality})` : ''}
            {record.details.view ? ` · ${record.details.view} view` : ''}
            {record.details.body_part_source === 'patient_confirmed' ? ' · confirmed by patient' : ''}
          </div>
        )}
        <div className="record-source-row">
          <span className="record-source">{SOURCE_LABEL[record.source_type] || record.source_type}</span>
          {record.source_document_id && <ViewSourceButton documentId={record.source_document_id} />}
        </div>
        {children}
      </div>
    </div>
  );
}
