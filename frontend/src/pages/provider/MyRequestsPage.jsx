import { useEffect, useState, useCallback } from 'react';
import { api } from '../../api';
import Badge from '../../components/Badge';

export default function MyRequestsPage({ onOpenPatient, refreshKey }) {
  const [grants, setGrants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.listMyGrantsAsProvider();
      setGrants(data);
    } catch (err) {
      setError(err.detail || 'Could not load your requests.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  return (
    <div>
      <div className="page-header">
        <h1>My requests</h1>
        <p>Patients you've requested access to, and the status of each request.</p>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && (
        grants.length === 0 ? (
          <div className="empty-state">
            You haven't requested access to any patients yet. Use "Find a patient" to get started.
          </div>
        ) : (
          grants.map((g) => (
            <div className="list-row" key={g.id}>
              <div className="row-main">
                <div className="row-title">{g.patient_name}</div>
                <div className="row-sub">
                  {g.patient_email}
                  {g.scope && g.scope.length > 0 ? ` · sharing: ${g.scope.join(', ')}` : ''}
                </div>
              </div>
              <div className="row-actions">
                <Badge status={g.status} />
                {g.status === 'approved' && (
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => onOpenPatient({ id: g.patient_id, name: g.patient_name })}
                  >
                    View patient
                  </button>
                )}
              </div>
            </div>
          ))
        )
      )}
    </div>
  );
}
