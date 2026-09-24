import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { parseUtc } from '../grants';

const TABS = [
  { key: 'pending', label: 'Waiting for review' },
  { key: 'verified', label: 'Verified' },
  { key: 'rejected', label: 'Not approved' },
  { key: 'not_submitted', label: 'Not submitted' },
];
const STATUS_TEXT = {
  pending: 'Under review', verified: '✓ Verified doctor', rejected: 'Not approved', not_submitted: 'Not submitted',
};
const NMC_REGISTER = 'https://www.nmc.org.in/information-desk/indian-medical-register/';

function when(value) {
  const d = parseUtc(value);
  return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}

function Field({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children || '—'}</dd>
    </div>
  );
}

function DoctorCard({ doctor, isSelf, onDecided }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [certError, setCertError] = useState('');

  const openCertificate = async () => {
    setCertError('');
    try {
      const url = URL.createObjectURL(await api.reviewerCertificateBlob(doctor.id));
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setCertError(err.detail || 'Could not open the certificate.');
    }
  };

  const decide = async (decision) => {
    setError('');
    if (decision === 'reject' && note.trim().length < 5) {
      setError('Write the reason the doctor will see (at least 5 characters).');
      return;
    }
    if (decision === 'approve' && !window.confirm(`Approve ${doctor.name} as a verified doctor? They'll be able to add patients.`)) return;
    setBusy(true);
    try {
      await api.reviewerDecide(doctor.id, decision, note.trim());
      setNote('');
      onDecided();
    } catch (err) {
      setError(typeof err.detail === 'string' ? err.detail : 'Could not save the decision.');
    } finally {
      setBusy(false);
    }
  };

  const submitted = doctor.status !== 'not_submitted';
  return (
    <article className={`review-card status-${doctor.status}`}>
      <header className="review-card-head">
        <div>
          <div className="review-name">{doctor.name}</div>
          <div className="muted" style={{ fontSize: '0.85rem' }}>
            {doctor.email}{doctor.email_verified ? ' · email verified' : ' · email not verified'}
          </div>
        </div>
        <span className={`verification-status ${doctor.status}`}>{STATUS_TEXT[doctor.status]}</span>
      </header>

      {!submitted ? (
        <p className="muted" style={{ fontSize: '0.88rem', margin: 0 }}>
          Registered {when(doctor.registered_at)}. They haven't filled in My Profile yet, so there's nothing to review.
        </p>
      ) : (
        <>
          <dl className="review-fields">
            <Field label="Specialization">{doctor.specialty}</Field>
            <Field label="Hospital / clinic">{doctor.hospital_name}</Field>
            <Field label="Registration number">{doctor.registration_number}</Field>
            <Field label="Medical council">{doctor.medical_council}</Field>
            <Field label="Year of registration">{doctor.registration_year}</Field>
            <Field label="Qualifications">{doctor.qualification}</Field>
            <Field label="Experience">
              {doctor.years_of_experience != null &&
                `${doctor.years_of_experience} years (since ${doctor.practice_start_year || doctor.registration_year})`}
            </Field>
            <Field label="Other affiliations">{doctor.affiliations.join('; ')}</Field>
            <Field label="Education">
              {doctor.education.map((e) => `${e.degree}, ${e.institution}${e.year ? ` (${e.year})` : ''}`).join('; ')}
            </Field>
            <Field label="Submitted">{when(doctor.submitted_at)}</Field>
          </dl>

          <div className="review-actions-row">
            {doctor.has_certificate ? (
              <button type="button" className="btn btn-secondary btn-sm" onClick={openCertificate}>
                📄 Open certificate ({doctor.certificate_file_name})
              </button>
            ) : (
              <span className="error-text">No certificate uploaded</span>
            )}
            <a className="btn btn-secondary btn-sm" href={NMC_REGISTER} target="_blank" rel="noreferrer">
              🔎 Check the NMC register
            </a>
            {certError && <span className="error-text">{certError}</span>}
          </div>

          <details className="review-checks">
            <summary>
              Automatic checks: <strong>{doctor.compliance.checks.filter((c) => c.passed).length} of {doctor.compliance.checks.length} met</strong>
            </summary>
            <ul>
              {doctor.compliance.checks.map((c) => (
                <li key={c.label}>
                  {c.passed ? <span className="check-pass">✓</span> : <span className={c.required ? 'check-fail' : 'check-optional'}>✗</span>}{' '}
                  {c.label}{!c.required && ' (recommended)'} <span className="muted">— {c.detail}</span>
                </li>
              ))}
            </ul>
          </details>

          {doctor.reviewed_at && (
            <p className="muted" style={{ fontSize: '0.84rem', margin: '0.2rem 0 0' }}>
              Last decision {when(doctor.reviewed_at)} by {doctor.reviewer}{doctor.review_note ? ` — “${doctor.review_note}”` : ''}
            </p>
          )}

          {isSelf ? (
            <p className="muted" style={{ fontSize: '0.84rem' }}>This is your own account; another reviewer has to decide.</p>
          ) : (
            <div className="review-decision">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={doctor.status === 'pending'
                  ? 'Note (optional when approving, required when rejecting), e.g. "Checked NMC register"'
                  : 'Reason for changing the decision'}
                aria-label={`Review note for ${doctor.name}`}
              />
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {doctor.status !== 'verified' && (
                  <button className="btn btn-primary btn-sm" onClick={() => decide('approve')} disabled={busy}>✓ Approve</button>
                )}
                {doctor.status !== 'rejected' && (
                  <button className="btn btn-danger btn-sm" onClick={() => decide('reject')} disabled={busy}>
                    {doctor.status === 'verified' ? 'Revoke verification' : '✗ Reject'}
                  </button>
                )}
              </div>
              {error && <p className="error-text">{error}</p>}
            </div>
          )}
        </>
      )}
    </article>
  );
}

/**
 * Reviewer screen: approve or reject doctor verification requests.
 * Shown only to accounts listed in MEDIPASS_REVIEWER_EMAILS on the server
 * (backend routers/reviewer.py); replaces the review_doctors.py command line.
 */
export default function ReviewDoctorsPage({ onChanged }) {
  const [tab, setTab] = useState('pending');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(() => api.reviewerListDoctors(tab)
    .then((d) => { setData(d); setError(''); })
    .catch((err) => setError(err.detail || 'Could not load doctors.')), [tab]);

  useEffect(() => {
    load();
  }, [load]);

  const decided = () => {
    load();
    onChanged?.();
  };

  return (
    <div>
      <div className="page-header">
        <h1>Review doctors</h1>
        <p>
          Check each doctor's registration against the medical council register and their certificate, then
          approve or reject. Approved doctors can add patients; the doctor is notified either way.
        </p>
      </div>

      <div className="ap-filters" role="tablist" aria-label="Verification status">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`ap-filter ${tab === t.key ? 'selected' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {data && <span className="ap-filter-count">{data.counts[t.key]}</span>}
          </button>
        ))}
      </div>

      {error && <p className="error-text">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && data.doctors.length === 0 && (
        <div className="empty-state">
          {tab === 'pending' ? 'No doctors are waiting for review.' : 'No doctors here.'}
        </div>
      )}
      {data?.doctors.map((d) => (
        <DoctorCard key={d.id} doctor={d} isSelf={d.id === data.you} onDecided={decided} />
      ))}
    </div>
  );
}
