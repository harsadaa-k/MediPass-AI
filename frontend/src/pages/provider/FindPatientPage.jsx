import { useState } from 'react';
import { api } from '../../api';

export default function FindPatientPage({ onRequested }) {
  const [email, setEmail] = useState('');
  const [patient, setPatient] = useState(null);
  const [error, setError] = useState('');
  const [searching, setSearching] = useState(false);
  const [requested, setRequested] = useState(false);
  const [requesting, setRequesting] = useState(false);

  const search = async (e) => {
    if (e) e.preventDefault();
    setError('');
    setPatient(null);
    setRequested(false);
    if (!email) return;

    setSearching(true);
    try {
      const found = await api.lookupPatient(email);
      setPatient(found);
    } catch (err) {
      setError(err.detail || 'No patient found with that email.');
    } finally {
      setSearching(false);
    }
  };

  const requestAccess = async () => {
    setRequesting(true);
    setError('');
    try {
      await api.requestAccess(patient.id);
      setRequested(true);
      if (onRequested) onRequested();
    } catch (err) {
      setError(err.detail || 'Could not send the request.');
    } finally {
      setRequesting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Find a patient</h1>
        <p>Look a patient up by email, then request access to their history. They'll decide what to share.</p>
      </div>

      <div className="surface" style={{ maxWidth: 480 }}>
        <form onSubmit={search}>
          <div className="field">
            <label htmlFor="patientEmail">Patient email</label>
            <input
              id="patientEmail"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="patient@example.com"
              required
            />
          </div>
          <button type="submit" className="btn btn-secondary" disabled={searching}>
            {searching ? 'Searching…' : 'Find patient'}
          </button>
        </form>

        {error && <p className="error-text" style={{ marginTop: '0.8rem' }}>{error}</p>}

        {patient && (
          <div className="list-row" style={{ marginTop: '1rem' }}>
            <div className="row-main">
              <div className="row-title">{patient.full_name}</div>
              <div className="row-sub">{patient.email}</div>
            </div>
            <div className="row-actions">
              {requested ? (
                <span className="muted" style={{ fontSize: '0.9rem' }}>Requested!</span>
              ) : (
                <button
                  className="btn btn-primary btn-sm"
                  onClick={requestAccess}
                  disabled={requesting}
                >
                  {requesting ? 'Requesting…' : 'Request access'}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

