import { useEffect, useState, useCallback } from 'react';
import { api } from '../../api';
import ViewSourceButton from '../../components/ViewSourceButton';
import { ConsultationContents, LinkConfirmButtons } from '../../components/RelatedLinks';
import { useAuth } from '../../AuthContext';
import CourseInfo from '../../components/CourseInfo';
import ConfidenceBadge from '../../components/ConfidenceBadge';
import { LOW_CONFIDENCE } from '../../confidence';
import { formatDay, plural, todayISO } from '../../dates';
import PrescriberEditor from '../../components/PrescriberEditor';

function EditableFields({ record, draft, setDraft }) {
  if (record.record_type === 'medication') {
    return (
      <>
        <div className="field">
          <label>Medicine</label>
          <input
            value={draft.medicine ?? record.details.medicine ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, medicine: e.target.value }))}
          />
        </div>
        <div className="field">
          <label>Dose</label>
          <input
            value={draft.dose ?? record.details.dose ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, dose: e.target.value }))}
          />
        </div>
        <div className="field">
          <label>Timing</label>
          <input
            value={draft.timing ?? record.details.timing ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, timing: e.target.value }))}
            placeholder="e.g. Morning, Night"
          />
        </div>
        <div className="field">
          <label>Duration</label>
          <input
            value={draft.duration ?? record.details.duration ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, duration: e.target.value }))}
            placeholder="e.g. 10 days, 2 weeks, 1 month"
          />
        </div>
        <div className="field">
          <label>Intake Status</label>
          <input
            value={draft.intake_status ?? record.details.intake_status ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, intake_status: e.target.value }))}
            placeholder="e.g. Before food"
          />
        </div>
      </>
    );
  }
  return (
    <div className="field">
      <label>Text</label>
      <input
        value={draft.text ?? record.details.text ?? ''}
        onChange={(e) => setDraft((d) => ({ ...d, text: e.target.value }))}
      />
    </div>
  );
}

const BODY_PART_SOURCE = {
  ai: 'Suggested by AI from the image',
  'dicom_metadata+ai': "The file's DICOM tag and the AI agree",
  dicom_metadata: "Taken from the file's DICOM tag",
  ocr_label: 'Read from a label printed on the image',
  conflict: 'The DICOM tag and the AI disagree',
  none: "Couldn't be identified automatically",
};

function BodyPartPicker({ record, bodyParts, value, onChange }) {
  const d = record.details || {};
  const unknown = !value || value === 'unknown';
  return (
    <div className="field" style={{ maxWidth: 360 }}>
      <label htmlFor={`bp-${record.id}`}>Body part shown in this image</label>
      <select id={`bp-${record.id}`} value={unknown ? '' : value} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>Choose a body part…</option>
        {bodyParts.map((bp) => (
          <option key={bp.code} value={bp.code}>{bp.label}</option>
        ))}
      </select>
      <span className="muted" style={{ fontSize: '0.8rem' }}>
        {[
          BODY_PART_SOURCE[d.body_part_source],
          d.body_part_note,
          unknown ? 'Please choose the correct body part before confirming' : '',
        ].filter(Boolean).join('. ')}.
      </span>
    </div>
  );
}

function VerifyCard({ record, onDone, bodyParts }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  // Only lab results can be images (X-ray/scan); a prescription photo's
  // medicines, diagnoses and advice never need a body part.
  const isImaging = record.record_type === 'lab_result' && record.details && 'body_part' in record.details;
  const [bodyPart, setBodyPart] = useState(record.details?.body_part || 'unknown');
  const [recordDate, setRecordDate] = useState(record.record_date);
  const today = todayISO(); // local YYYY-MM-DD
  const dateChanged = recordDate && recordDate !== record.record_date;
  const withDate = (body) => (dateChanged ? { ...body, corrected_record_date: recordDate } : body);
  const needsBodyPart = isImaging && (!bodyPart || bodyPart === 'unknown');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const confirmAsIs = async () => {
    setSubmitting(true);
    setError('');
    try {
      // Imaging: always send the body part the patient saw/selected.
      await api.verifyRecord(record.id, withDate(isImaging ? { corrected_details: { ...record.details, body_part: bodyPart } } : {}));
      onDone(record.id);
    } catch (err) {
      setError(err.detail || 'Could not verify this record.');
    } finally {
      setSubmitting(false);
    }
  };

  const confirmWithEdits = async () => {
    setSubmitting(true);
    setError('');
    try {
      let correctedDetails;
      if (record.record_type === 'medication') {
        correctedDetails = {
          ...record.details,
          medicine: draft.medicine ?? record.details.medicine,
          dose: draft.dose ?? record.details.dose,
          timing: draft.timing ?? record.details.timing,
          intake_status: draft.intake_status ?? record.details.intake_status,
          duration: draft.duration ?? record.details.duration,
        };
      } else {
        correctedDetails = { ...record.details, text: draft.text ?? record.details.text };
      }
      if (isImaging) correctedDetails.body_part = bodyPart;
      await api.verifyRecord(record.id, withDate({ corrected_details: correctedDetails }));
      onDone(record.id);
    } catch (err) {
      setError(err.detail || 'Could not save your correction.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async () => {
    if (!window.confirm("Are you sure you want to remove this record?")) return;
    setSubmitting(true);
    setError('');
    try {
      await api.deleteRecord(record.id);
      onDone(record.id);
    } catch (err) {
      setError(err.detail || 'Could not remove this record.');
    } finally {
      setSubmitting(false);
    }
  };

  const lowConfidence = record.confidence != null && record.confidence < LOW_CONFIDENCE;
  const missing = record.details?.confidence_basis?.missing || [];

  return (
    <div className="verify-card">
      <div className="verify-top">
        <div>
          <div style={{ fontWeight: 600 }}>{record.title}</div>
          <div className="muted" style={{ fontSize: '0.85rem' }}>
            {record.record_type.replace('_', ' ')} · {record.record_date}
            {record.details?.is_fallback_date && (
              <span className="badge badge-amber" style={{ marginLeft: '8px' }}>
                Date not on document
              </span>
            )}
          </div>
        </div>
        <ConfidenceBadge record={record} />
      </div>

      {record.duplicate_of && (
        <div className="duplicate-note" role="note">
          <span>
            ⚠ Looks like a duplicate of <strong>{record.duplicate_of.title}</strong> ({formatDay(record.duplicate_of.record_date)}),
            already on your timeline.
          </span>
          <button className="btn btn-danger btn-sm" onClick={handleRemove} disabled={submitting}>Remove duplicate</button>
        </div>
      )}

      {lowConfidence && (
        <p style={{ fontSize: '0.85rem', color: 'var(--amber)', margin: '0 0 0.6rem 0' }}>
          Low confidence — please check this carefully before confirming.
          {missing.length > 0 && ` Missing or unclear: ${missing.join(', ')}.`}
        </p>
      )}

      {record.source_document_id && (
        <div style={{ marginBottom: '0.6rem' }}>
          <ViewSourceButton documentId={record.source_document_id} />
        </div>
      )}

      {!editing && record.record_type === 'medication' && (
        <div style={{ fontSize: '0.88rem', color: 'var(--text-muted)', marginBottom: '0.6rem', display: 'flex', flexWrap: 'wrap', gap: '0.6rem 1.2rem' }}>
          {record.details?.medicine && <span><strong>Medicine:</strong> {record.details.medicine}</span>}
          {record.details?.dose && <span><strong>Dose:</strong> {record.details.dose}</span>}
          {record.details?.timing && <span><strong>Timing:</strong> {record.details.timing}</span>}
          {record.details?.intake_status && <span><strong>Intake Status:</strong> {record.details.intake_status}</span>}
          {record.course && (
            <span>
              <strong>Course:</strong>{' '}
              {dateChanged && !record.course.ongoing
                ? `${plural(record.course.duration_days, 'day')} from the date below (end date updates when you confirm)`
                : <CourseInfo course={record.course} />}
            </span>
          )}
          {!record.course && record.details?.duration && <span><strong>Duration:</strong> {record.details.duration}</span>}
        </div>
      )}

      <div className="field" style={{ maxWidth: 220 }}>
        <label htmlFor={`date-${record.id}`}>
          {record.record_type === 'lab_result' ? 'Report date' : 'Consultation date'}
        </label>
        <input
          id={`date-${record.id}`}
          type="date"
          value={recordDate}
          max={today}
          onChange={(e) => setRecordDate(e.target.value)}
        />
        <span className="muted" style={{ fontSize: '0.8rem' }}>
          {record.details?.is_fallback_date && !dateChanged
            ? 'No date was found on the document — please enter the date written on it.'
            : 'Check this matches the date written on the document.'}
        </span>
      </div>

      {isImaging && (
        <BodyPartPicker record={record} bodyParts={bodyParts} value={bodyPart} onChange={setBodyPart} />
      )}

      {editing && <EditableFields record={record} draft={draft} setDraft={setDraft} />}

      {error && <p className="error-text">{error}</p>}

      <div className="verify-actions">
        {!editing ? (
          <>
            <button className="btn btn-primary btn-sm" onClick={confirmAsIs} disabled={submitting || needsBodyPart}>
              {isImaging ? 'Confirm' : 'Confirm as-is'}
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>
              Edit before confirming
            </button>
            <button className="btn btn-danger btn-sm" onClick={handleRemove} disabled={submitting}>
              Remove
            </button>
          </>
        ) : (
          <>
            <button className="btn btn-primary btn-sm" onClick={confirmWithEdits} disabled={submitting || needsBodyPart}>
              Save correction and confirm
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function PendingLinks({ onChanged }) {
  const { user } = useAuth();
  const [links, setLinks] = useState([]);

  const load = useCallback(async () => {
    try {
      const all = await api.getRecordLinks(user.id);
      setLinks(all.filter((l) => l.status === 'linked' && l.document));
    } catch {
      setLinks([]);
    }
  }, [user.id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!links.length) return null;
  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <h2 style={{ fontSize: '1.1rem', margin: '0 0 0.6rem' }}>Confirm document links ({links.length})</h2>
      <p className="muted" style={{ fontSize: '0.88rem', marginTop: 0 }}>
        MediPass matched these consultation notes to prescriptions from the same doctor. Once you confirm a link
        it's final.
      </p>
      {links.map((l) => (
        <div key={l.id} className="link-confirm-card">
          <div style={{ fontWeight: 600 }}>
            {l.consultation.title} <span className="muted" style={{ fontWeight: 400 }}>
              · note by Dr. {l.consultation.author_name?.replace(/^dr\.?\s*/i, '')} · {l.consultation.date}
            </span>
          </div>
          <ConsultationContents note={l.consultation} />
          <div style={{ fontSize: '0.88rem', margin: '0.3rem 0 0.5rem' }}>
            🔗 Prescription: <strong>{l.document.doctor || 'Prescription'}</strong>
            {l.document.hospital ? ` (${l.document.hospital})` : ''}{l.document.date ? ` · ${l.document.date}` : ''}
            {l.document.medicines?.length ? ` · ${l.document.medicines.slice(0, 3).join(', ')}` : ''}
            <div className="muted" style={{ fontSize: '0.8rem' }}>
              {l.method === 'manual' ? `Linked by ${l.overridden_by}: “${l.override_reason}”` : `Why: ${l.match_reason}`}
              {' '}· <span className="mono">{l.ref}</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.8rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <ViewSourceButton documentId={l.document.id} />
            <LinkConfirmButtons link={l} onChanged={() => { load(); onChanged?.(); }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function VerifyQueue({ onVerified }) {
  const [records, setRecords] = useState([]);
  const [docTypes, setDocTypes] = useState({});
  const [bodyParts, setBodyParts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.listUnverified();
      setRecords(data);
      // which uploads are prescriptions (they get the "Prescribed by" box)
      const ids = [...new Set(data.map((r) => r.source_document_id).filter(Boolean))];
      const docs = await Promise.all(ids.map((id) => api.getDocument(id).catch(() => null)));
      setDocTypes(Object.fromEntries(docs.filter(Boolean).map((d) => [d.id, d.document_type])));
    } catch (err) {
      setError(err.detail || 'Could not load records to verify.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.listBodyParts().then(setBodyParts).catch(() => setBodyParts([]));
  }, []);

  const handleDone = (id) => {
    setRecords((prev) => prev.filter((r) => r.id !== id));
    if (onVerified) onVerified();
  };

  return (
    <div>
      <div className="page-header">
        <h1>Verify records</h1>
        <p>Check what MediPass pulled from your uploaded documents before it joins your timeline.</p>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error-text">{error}</p>}

      <PendingLinks onChanged={onVerified} />

      {!loading && !error && records.length === 0 && (
        <div className="empty-state">Nothing waiting for review right now.</div>
      )}

      {records.map((record, i) => {
        const docId = record.source_document_id;
        const firstOfDoc = docId && records.findIndex((r) => r.source_document_id === docId) === i;
        const d = record.details || {};
        return (
          <div key={record.id}>
            {firstOfDoc && docTypes[docId] === 'prescription' && (
              <div className="verify-doc-box">
                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                  PRESCRIPTION · check who wrote it (used to link your doctor's consultation notes)
                </div>
                <PrescriberEditor
                  documentId={docId}
                  doctor={d.doctor_name || ''}
                  hospital={d.hospital_name || ''}
                  startOpen={!d.doctor_name}
                  onSaved={load}
                />
              </div>
            )}
            <VerifyCard record={record} onDone={handleDone} bodyParts={bodyParts} />
          </div>
        );
      })}
    </div>
  );
}
