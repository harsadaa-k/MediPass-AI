import { useState } from 'react';
import { api } from '../../api';
import VoiceDictation from '../../components/VoiceDictation';
import { todayISO } from '../../dates';

const RECORD_TYPES = [
  { value: 'consultation', label: 'Consultation note' },
  { value: 'diagnosis', label: 'Diagnosis' },
  { value: 'medication', label: 'Medication / prescription' },
  { value: 'lab_result', label: 'Lab result' },
  { value: 'hospitalization', label: 'Hospitalization' },
  { value: 'allergy', label: 'Allergy' },
];

// local calendar day (toISOString() is the UTC day: yesterday before 05:30 in India)
const today = () => todayISO();

export default function AddConsultationForm({ patientId, onAdded }) {
  const [recordType, setRecordType] = useState('consultation');
  const [title, setTitle] = useState('');
  const [recordDate, setRecordDate] = useState(today());
  const [medicine, setMedicine] = useState('');
  const [dose, setDose] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const buildDetails = () => {
    if (recordType === 'medication') return { medicine, dose };
    if (recordType === 'consultation' || recordType === 'hospitalization') return { notes: text };
    return { text };
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess(false);
    setSubmitting(true);
    try {
      await api.addConsultation({
        patient_id: patientId,
        record_type: recordType,
        title,
        details: buildDetails(),
        record_date: recordDate,
      });
      setSuccess(true);
      setTitle('');
      setMedicine('');
      setDose('');
      setText('');
      if (onAdded) onAdded();
    } catch (err) {
      setError(err.detail || 'Could not add this record.');
    } finally {
      setSubmitting(false);
    }
  };

  /**
   * Called by VoiceDictation when the doctor clicks "Apply to form".
   * Pre-fills all form fields with the AI-structured result.
   */
  const handleVoiceApply = (structured) => {
    if (structured.record_type) {
      setRecordType(structured.record_type);
    }
    if (structured.title) {
      setTitle(structured.title);
    }
    if (structured.record_date) {
      setRecordDate(structured.record_date);
    }
    if (structured.details) {
      if (structured.record_type === 'medication') {
        setMedicine(structured.details.medicine || '');
        setDose(structured.details.dose || '');
      } else {
        // For non-medication types, combine notes/text/follow_up into the text field
        const parts = [];
        if (structured.details.notes) parts.push(structured.details.notes);
        if (structured.details.text) parts.push(structured.details.text);
        if (structured.details.follow_up) parts.push(`Follow-up: ${structured.details.follow_up}`);
        setText(parts.join('\n'));
      }
    }
    setSuccess(false);
    setError('');
  };

  return (
    <div className="surface" style={{ maxWidth: 520 }}>
      <div className="consultation-form-header">
        <h3>Add a record</h3>
        <VoiceDictation onApply={handleVoiceApply} />
      </div>

      <hr style={{ margin: '1rem 0' }} />

      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="recordType">Record type</label>
          <select id="recordType" value={recordType} onChange={(e) => setRecordType(e.target.value)}>
            {RECORD_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="title">Title</label>
          <input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Follow-up consultation"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="recordDate">Date</label>
          <input
            id="recordDate"
            type="date"
            value={recordDate}
            onChange={(e) => setRecordDate(e.target.value)}
            required
          />
        </div>

        {recordType === 'medication' ? (
          <>
            <div className="field">
              <label htmlFor="medicine">Medicine</label>
              <input id="medicine" value={medicine} onChange={(e) => setMedicine(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="dose">Dose</label>
              <input id="dose" value={dose} onChange={(e) => setDose(e.target.value)} placeholder="e.g. 500mg" required />
            </div>
          </>
        ) : (
          <div className="field">
            <label htmlFor="details">Details</label>
            <textarea
              id="details"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="What should the patient's record say?"
              required
            />
          </div>
        )}

        {error && <p className="error-text">{error}</p>}
        {success && <p style={{ color: 'var(--softgreen)', fontWeight: 600 }}>Added to the patient's timeline.</p>}

        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Adding…' : 'Add to timeline'}
        </button>
      </form>
    </div>
  );
}


