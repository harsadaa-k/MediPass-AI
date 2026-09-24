import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';

const NMC_REGISTER = 'https://www.nmc.org.in/information-desk/indian-medical-register/';

function Row({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children || '—'}</dd>
    </div>
  );
}

/**
 * Opened from the reviewer email's Approve / Reject button. No login: the
 * signed token in the link is the permission, and it only works for that one
 * verification request. Nothing changes until the reviewer confirms here, so
 * mail scanners that open links can't approve anyone.
 */
export default function ReviewDecisionPage() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [decision, setDecision] = useState(params.get('action') === 'reject' ? 'reject' : 'approve');
  const [info, setInfo] = useState(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState(token ? '' : 'This link is missing its review code.');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    if (!token) return;
    api.emailReviewDetails(token)
      .then(setInfo)
      .catch((err) => setLoadError(typeof err.detail === 'string' ? err.detail : 'This review link could not be opened.'));
  }, [token]);

  const openCertificate = async () => {
    try {
      const url = URL.createObjectURL(await api.emailReviewCertificateBlob(token));
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(err.detail || 'Could not open the certificate.');
    }
  };

  const confirm = async () => {
    setError('');
    if (decision === 'reject' && note.trim().length < 5) {
      setError('Write the reason the doctor will see (at least 5 characters).');
      return;
    }
    setBusy(true);
    try {
      setDone(await api.emailReviewDecide(token, decision, note.trim()));
    } catch (err) {
      setError(typeof err.detail === 'string' ? err.detail : 'Could not save the decision.');
    } finally {
      setBusy(false);
    }
  };

  const d = info?.doctor;
  return (
    <div className="auth-screen">
      <div style={{ width: '100%', maxWidth: 640 }}>
        <div className="auth-brand">
          <div className="name">MediPass</div>
          <div className="tagline">Doctor verification review</div>
        </div>

        <div className="surface">
          {loadError && <p className="error-text">{loadError}</p>}
          {!loadError && !info && <p className="muted">Loading…</p>}

          {done && (
            <div role="status">
              <h2 style={{ marginBottom: '0.4rem' }}>
                {done.status === 'verified' ? '✓ Doctor approved' : '✗ Verification rejected'}
              </h2>
              <p>
                <strong>{done.name}</strong> is now <strong>{done.status === 'verified' ? 'a verified doctor' : 'not approved'}</strong>.
                They've been notified{done.status === 'verified' ? ' and can now add patients' : ' with your reason'}.
              </p>
              <p className="muted" style={{ fontSize: '0.85rem' }}>You can close this page.</p>
            </div>
          )}

          {info && !done && (
            <>
              <div className="review-card-head">
                <div>
                  <div className="review-name">{d.name}</div>
                  <div className="muted" style={{ fontSize: '0.85rem' }}>{d.email}</div>
                </div>
                <span className={`verification-status ${d.status}`}>
                  {{ pending: 'Under review', verified: '✓ Verified', rejected: 'Not approved' }[d.status] || d.status}
                </span>
              </div>

              <dl className="review-fields">
                <Row label="Specialization">{d.specialty}</Row>
                <Row label="Hospital / clinic">{d.hospital_name}</Row>
                <Row label="Registration number">{d.registration_number}</Row>
                <Row label="Medical council">{d.medical_council}</Row>
                <Row label="Year of registration">{d.registration_year}</Row>
                <Row label="Qualifications">{d.qualification}</Row>
                <Row label="Education">
                  {d.education.map((e) => `${e.degree}, ${e.institution}${e.year ? ` (${e.year})` : ''}`).join('; ')}
                </Row>
                <Row label="Experience">{d.years_of_experience != null && `${d.years_of_experience} years`}</Row>
              </dl>

              <div className="review-actions-row">
                {d.has_certificate && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={openCertificate}>
                    📄 Open certificate
                  </button>
                )}
                <a className="btn btn-secondary btn-sm" href={NMC_REGISTER} target="_blank" rel="noreferrer">
                  🔎 Check the NMC register
                </a>
              </div>

              {info.stale ? (
                <p className="error-text">
                  The doctor changed their details after this email was sent. Use the newer email to decide.
                </p>
              ) : info.decided ? (
                <p className="muted">
                  Already decided: <strong>{d.status}</strong>{d.reviewer ? ` by ${d.reviewer}` : ''}
                  {d.review_note ? ` — “${d.review_note}”` : ''}. Nothing more to do.
                </p>
              ) : (
                <div className="review-decision">
                  <div className="role-picker" role="radiogroup" aria-label="Decision">
                    <button type="button" className={`role-option ${decision === 'approve' ? 'selected' : ''}`}
                            aria-pressed={decision === 'approve'} onClick={() => setDecision('approve')}>
                      ✓ Approve
                    </button>
                    <button type="button" className={`role-option ${decision === 'reject' ? 'selected' : ''}`}
                            aria-pressed={decision === 'reject'} onClick={() => setDecision('reject')}>
                      ✗ Reject
                    </button>
                  </div>
                  <textarea
                    rows={2}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    aria-label="Note for the doctor"
                    placeholder={decision === 'reject'
                      ? 'Reason the doctor will see (required), e.g. "Registration number not found"'
                      : 'Note (optional), e.g. "Checked NMC register"'}
                  />
                  <button className={`btn ${decision === 'approve' ? 'btn-primary' : 'btn-danger'}`}
                          onClick={confirm} disabled={busy}>
                    {busy ? 'Saving…' : decision === 'approve' ? `Confirm: approve ${d.name}` : `Confirm: reject ${d.name}`}
                  </button>
                  <span className="muted" style={{ fontSize: '0.8rem' }}>Reviewing as {info.reviewer_email}</span>
                </div>
              )}
              {error && <p className="error-text">{error}</p>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
