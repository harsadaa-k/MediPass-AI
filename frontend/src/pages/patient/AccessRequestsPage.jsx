import { useEffect, useState, useCallback } from 'react';
import { api } from '../../api';
import Badge from '../../components/Badge';

const SCOPE_OPTIONS = ['medications', 'labs', 'allergies', 'diagnoses', 'full_history'];

function PendingRequestRow({ grant, onResponded }) {
  const [selectedScope, setSelectedScope] = useState([]);
  const [expiryDays, setExpiryDays] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  
  const [aiRec, setAiRec] = useState(null);
  const [loadingAi, setLoadingAi] = useState(false);

  useEffect(() => {
    // Automatically fetch AI recommendation on mount
    const fetchAi = async () => {
      setLoadingAi(true);
      try {
        const data = await api.getAiSharingRecommendation(grant.id);
        setAiRec(data);
      } catch (err) {
        console.error("Failed to fetch AI recommendation", err);
      } finally {
        setLoadingAi(false);
      }
    };
    fetchAi();
  }, [grant.id]);

  const toggleScope = (scope) => {
    setSelectedScope((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  };
  
  const applyAiSuggestion = () => {
    if (aiRec && aiRec.recommended_scopes) {
      setSelectedScope(aiRec.recommended_scopes);
    }
  };

  const respond = async (approve) => {
    setSubmitting(true);
    setError('');
    try {
      await api.respondToRequest(grant.id, approve, approve ? selectedScope : [], approve ? expiryDays : 30);
      onResponded();
    } catch (err) {
      setError(err.detail || 'Could not respond to this request.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="list-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div className="row-main">
          <div className="row-title">{grant.provider_name}
            {grant.provider_verified
            ? <span className="badge badge-green" style={{ marginLeft: '0.5rem' }} title="Registration checked by MediPass">✓ Verified doctor</span>
            : <span className="badge badge-amber" style={{ marginLeft: '0.5rem' }} title="This doctor's registration hasn't been verified">Not verified</span>}
          </div>
          <div className="row-sub">
            {grant.provider_email} wants access to your records
            {grant.provider_specialty && ` · Specialty: ${grant.provider_specialty}`}
            {grant.provider_hospital && ` · ${grant.provider_hospital}`}
          </div>
        </div>
        <Badge status={grant.status} />
      </div>

      <div style={{ marginTop: '0.6rem', padding: '0.8rem', backgroundColor: '#f0f4f8', borderRadius: 'var(--radius)', border: '1px solid #cce3f6' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
          <strong>✨ AI Sharing Recommendation</strong>
          {loadingAi && <span className="muted" style={{ fontSize: '0.8rem' }}>Analyzing...</span>}
        </div>
        {aiRec ? (
          <>
            <p style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: '#334155' }}>{aiRec.explanation}</p>
            <button type="button" className="btn btn-sm" onClick={applyAiSuggestion} style={{ backgroundColor: '#e2e8f0', color: '#0f172a' }}>
              Select Recommended: {aiRec.recommended_scopes.join(', ')}
            </button>
          </>
        ) : (
          !loadingAi && <p className="muted" style={{ fontSize: '0.9rem' }}>No AI recommendation available.</p>
        )}
      </div>

      <div>
        <div className="row-sub" style={{ margin: '0.6rem 0 0.2rem' }}>
          Choose what to share
        </div>
        <div className="scope-picker">
          {SCOPE_OPTIONS.map((scope) => (
            <button
              key={scope}
              type="button"
              className={`scope-chip ${selectedScope.includes(scope) ? 'selected' : ''}`}
              onClick={() => toggleScope(scope)}
            >
              {scope.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>
      
      <div style={{ marginTop: '0.8rem' }}>
        <label className="row-sub" style={{ display: 'block', marginBottom: '0.2rem' }}>
          Access Duration
        </label>
        <select 
          value={expiryDays} 
          onChange={(e) => setExpiryDays(Number(e.target.value))}
          style={{ padding: '0.4rem', borderRadius: 'var(--radius)', border: '1px solid #ddd', fontSize: '0.9rem' }}
        >
          <option value={1}>24 Hours</option>
          <option value={7}>7 Days</option>
          <option value={30}>30 Days</option>
        </select>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="row-actions" style={{ marginTop: '1rem' }}>
        <button className="btn btn-primary btn-sm" onClick={() => respond(true)} disabled={submitting}>
          Approve access
        </button>
        <button className="btn btn-danger btn-sm" onClick={() => respond(false)} disabled={submitting}>
          Deny
        </button>
      </div>
    </div>
  );
}

function DecidedRequestRow({ grant, onRevoked }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const revoke = async () => {
    setSubmitting(true);
    setError('');
    try {
      await api.revokeAccess(grant.id);
      onRevoked();
    } catch (err) {
      setError(err.detail || 'Could not revoke access.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="list-row">
      <div className="row-main">
        <div className="row-title">{grant.provider_name}
          {grant.provider_verified
            ? <span className="badge badge-green" style={{ marginLeft: '0.5rem' }} title="Registration checked by MediPass">✓ Verified doctor</span>
            : <span className="badge badge-amber" style={{ marginLeft: '0.5rem' }} title="This doctor's registration hasn't been verified">Not verified</span>}
        </div>
        <div className="row-sub">
          {grant.provider_email}
          {grant.scope && grant.scope.length > 0 ? ` · sharing: ${grant.scope.join(', ')}` : ''}
        </div>
        {error && <p className="error-text">{error}</p>}
      </div>
      <div className="row-actions">
        <Badge status={grant.status} />
        {grant.status === 'approved' && (
          <button className="btn btn-danger btn-sm" onClick={revoke} disabled={submitting}>
            Revoke
          </button>
        )}
      </div>
    </div>
  );
}

export default function AccessRequestsPage({ onAction }) {
  const [grants, setGrants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.listMyGrantsAsPatient();
      setGrants(data);
    } catch (err) {
      setError(err.detail || 'Could not load access requests.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Refresh the list and let the dashboard refresh its sidebar badges.
  const handleChanged = () => {
    load();
    if (onAction) onAction();
  };


  const pending = grants.filter((g) => g.status === 'pending');
  const decided = grants.filter((g) => g.status !== 'pending');

  return (
    <div>
      <div className="page-header">
        <h1>Access requests</h1>
        <p>You decide who can see your history, and what parts of it they can see.</p>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && (
        <>
          <div className="section">
            <h2>Pending</h2>
            {pending.length === 0 ? (
              <div className="empty-state">No pending requests.</div>
            ) : (
              pending.map((g) => <PendingRequestRow key={g.id} grant={g} onResponded={handleChanged} />)
            )}
          </div>

          <div className="section">
            <h2>Doctors with access history</h2>
            {decided.length === 0 ? (
              <div className="empty-state">No decisions made yet.</div>
            ) : (
              decided.map((g) => <DecidedRequestRow key={g.id} grant={g} onRevoked={handleChanged} />)
            )}
          </div>
        </>
      )}
    </div>
  );
}
