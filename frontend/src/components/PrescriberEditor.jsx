import { useState } from 'react';
import { api } from '../api';

/**
 * "Prescribed by / Hospital" for one uploaded prescription. The AI often
 * can't read these (handwritten slips, online consults), and linking a
 * doctor's consultation note to the prescription needs the doctor's name.
 * Saving applies to every entry from the document and re-runs linking
 * (backend PATCH /documents/{id}/prescriber). Locked once a link to this
 * prescription has been confirmed.
 */
export default function PrescriberEditor({ documentId, doctor = '', hospital = '', locked = false, onSaved, startOpen = false }) {
  const [editing, setEditing] = useState(startOpen);
  const [doctorName, setDoctorName] = useState(doctor);
  const [hospitalName, setHospitalName] = useState(hospital);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState({ doctor, hospital });

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const r = await api.setPrescriber(documentId, doctorName, hospitalName);
      setSaved({ doctor: r.doctor_name, hospital: r.hospital_name });
      setDoctorName(r.doctor_name);
      setEditing(false);
      onSaved?.(r);
    } catch (err) {
      setError(typeof err.detail === 'string' ? err.detail : 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="prescriber-line">
        <span>
          Prescribed by <strong>{saved.doctor || 'unknown doctor'}</strong>
          {saved.hospital ? <> · {saved.hospital}</> : null}
        </span>
        {locked ? (
          <span className="muted" title="A confirmed link uses this prescription">🔒</span>
        ) : (
          <button type="button" className="link-edit-btn" onClick={() => setEditing(true)}>
            {saved.doctor ? 'Edit' : 'Add doctor'}
          </button>
        )}
      </div>
    );
  }

  return (
    <form className="prescriber-form" onSubmit={save}>
      <div className="prescriber-fields">
        <label>
          Prescribed by
          <input value={doctorName} onChange={(e) => setDoctorName(e.target.value)} placeholder="e.g. Dr. R. Mehta" />
        </label>
        <label>
          Hospital / clinic
          <input value={hospitalName} onChange={(e) => setHospitalName(e.target.value)} placeholder="As on the letterhead or stamp" />
        </label>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setEditing(false); setError(''); }}>
          Cancel
        </button>
      </div>
    </form>
  );
}
