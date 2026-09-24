import { useEffect, useState } from 'react';
import { useAuth } from '../../AuthContext';
import { api } from '../../api';
import { isActiveGrant, parseUtc } from '../../grants';
import ActivePatients from './ActivePatients';

export default function ProviderOverview({ onNavigate, onOpenPatient, justAdded, onDismissJustAdded, qrLinkError }) {
  const { user } = useAuth();
  const [grants, setGrants] = useState([]);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pickingPatient, setPickingPatient] = useState(false);
  const [verification, setVerification] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [g, r, v] = await Promise.all([
          api.listMyGrantsAsProvider(),
          api.listMyRecentConsultations(5),
          api.getMyVerification().catch(() => null),
        ]);
        setGrants(g);
        setRecent(r);
        setVerification(v);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <p className="muted">Loading dashboard…</p>;

  const active = grants.filter((g) => isActiveGrant(g));
  const pending = grants.filter((g) => g.status === 'pending');

  const openPatient = (patientId, name, focusConsultation = false) =>
    onOpenPatient({ id: patientId, name }, { focusConsultation });

  const handleAddConsultation = () => {
    if (active.length === 1) {
      openPatient(active[0].patient_id, active[0].patient_name, true);
    } else {
      setPickingPatient((v) => !v);
    }
  };

  const stats = [
    { label: 'Patients with active access', value: active.length, color: '#10b981' },
    { label: 'Pending requests', value: pending.length, color: '#f59e0b' },
    { label: 'Recent records you added', value: recent.length, color: '#6366f1' },
  ];

  const displayName = user.full_name.trim().toLowerCase().startsWith('dr')
    ? user.full_name
    : `Dr. ${user.full_name}`;

  return (
    <div>
      <div className="page-header">
        <h1>Welcome, {displayName}!</h1>
        <p>Your doctor dashboard at a glance.</p>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: '1rem',
        marginBottom: '1.5rem',
      }}>
        {stats.map((s) => (
          <div
            key={s.label}
            className="surface"
            style={{
              textAlign: 'center',
              padding: '1.25rem 1rem',
              borderTop: `3px solid ${s.color}`,
            }}
          >
            <div style={{ fontSize: '2rem', fontWeight: 700, color: s.color }}>{s.value}</div>
            <div className="muted" style={{ fontSize: '0.85rem', marginTop: '0.3rem' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {justAdded && (
        <div className="qr-added-banner" role="status">
          <div>
            <strong>✓ {justAdded.patient_name} {justAdded.already_had_access ? 'access renewed' : 'added to your patients'}</strong>
            <div style={{ fontSize: '0.85rem' }}>
              Via their QR code · sharing {justAdded.scope.join(', ').replace('_', ' ')}
              {justAdded.expires_at ? ` · until ${parseUtc(justAdded.expires_at).toLocaleDateString()}` : ''}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={() => openPatient(justAdded.patient_id, justAdded.patient_name)}
            >
              Open patient
            </button>
            <button className="btn btn-secondary btn-sm" onClick={onDismissJustAdded}>Dismiss</button>
          </div>
        </div>
      )}
      {qrLinkError && <p className="error-text">{qrLinkError}</p>}

      {verification && verification.status !== 'verified' && (
        <div className="verify-nudge" role="status">
          <div>
            <strong>
              {verification.status === 'pending' && '⏳ Your doctor verification is under review'}
              {verification.status === 'rejected' && '✗ Your doctor verification was not approved'}
              {verification.status === 'not_submitted' && '⚠ Verify your doctor profile'}
            </strong>
            <div style={{ fontSize: '0.85rem' }}>
              {verification.status === 'rejected' && verification.review_note ? `${verification.review_note}. ` : ''}
              {verification.verification_required
                ? 'You can add new patients once your specialization, hospital and medical registration are verified.'
                : 'Patients see whether your registration has been verified.'}
            </div>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => onNavigate('profile')}>
            {verification.status === 'pending' ? 'View details' : 'Go to My Profile'}
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '1rem' }}>
        <button className="btn btn-primary" onClick={() => onNavigate('scan')}>
          📷 Scan Patient QR
        </button>
        <button className="btn btn-secondary" onClick={() => onNavigate('find')}>
          Request Patient Access
        </button>
        <button
          className="btn btn-secondary"
          onClick={handleAddConsultation}
          disabled={active.length === 0}
          title={active.length === 0 ? 'You need an approved patient first' : undefined}
        >
          Add Consultation
        </button>
      </div>

      {pickingPatient && active.length > 1 && (
        <div className="surface" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ marginBottom: '0.75rem' }}>Add a consultation for…</h3>
          {active.map((g) => (
            <div key={g.id} className="list-row" style={{ padding: '0.5rem 0' }}>
              <div className="row-main">
                <div className="row-title">{g.patient_name}</div>
                <div className="row-sub">{g.patient_email}</div>
              </div>
              <div className="row-actions">
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => openPatient(g.patient_id, g.patient_name, true)}
                >
                  Select
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {pending.length > 0 && (
        <div className="surface" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ marginBottom: '0.75rem' }}>Waiting for patient approval</h3>
          {pending.map((g) => (
            <div key={g.id} className="list-row" style={{ padding: '0.6rem 0', borderBottom: '1px solid var(--border)' }}>
              <div className="row-main">
                <div className="row-title">{g.patient_name}</div>
                <div className="row-sub">
                  {g.patient_email} · requested {parseUtc(g.requested_at).toLocaleDateString()}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <ActivePatients
        onOpenPatient={(id, name) => openPatient(id, name)}
        highlightPatientId={justAdded?.patient_id}
      />

      <div className="surface">
        <h3 style={{ marginBottom: '0.75rem' }}>Recent consultations</h3>
        {recent.length === 0 ? (
          <p className="muted" style={{ fontSize: '0.88rem' }}>
            Records you add for patients with active access will show up here.
          </p>
        ) : (
          recent.map((r) => (
            <div key={r.id} className="list-row" style={{ padding: '0.6rem 0', borderBottom: '1px solid var(--border)' }}>
              <div className="row-main">
                <div className="row-title">{r.title}</div>
                <div className="row-sub">
                  {r.patient_name} · {r.record_type.replace('_', ' ')} · {r.record_date}
                </div>
              </div>
              <div className="row-actions">
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => openPatient(r.patient_id, r.patient_name)}
                >
                  Open
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
