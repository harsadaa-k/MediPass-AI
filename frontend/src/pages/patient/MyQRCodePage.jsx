import { useEffect, useState } from 'react';
import QRCode from 'react-qr-code';
import { api } from '../../api';
import { parseUtc } from '../../grants';

const SCOPE_OPTIONS = ['medications', 'labs', 'allergies', 'diagnoses', 'full_history'];
const ACCESS_OPTIONS = [7, 30, 90];
const VALIDITY_OPTIONS = [
  { minutes: 15, label: '15 minutes' },
  { minutes: 60, label: '1 hour' },
  { minutes: 1440, label: '24 hours' },
];
const POLL_MS = 3000;

function formatRemaining(ms) {
  if (ms <= 0) return 'expired';
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${m}m` : `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * The patient shows this QR code to a doctor. When the doctor scans it with
 * "Scan patient QR", the patient is added to the doctor's list straight away
 * with the sharing chosen here -- no access request to approve afterwards.
 */
export default function MyQRCodePage() {
  const [scope, setScope] = useState(['medications', 'allergies', 'diagnoses']);
  const [accessDays, setAccessDays] = useState(30);
  const [validMinutes, setValidMinutes] = useState(15);
  const [qr, setQr] = useState(null); // includes .token right after creation
  const [token, setToken] = useState('');
  const [shortCode, setShortCode] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const expiresAt = qr ? parseUtc(qr.expires_at).getTime() : 0;
  const live = qr && !qr.used_at && !qr.revoked && expiresAt > now;

  // Tick the countdown and poll for "scanned" while the code is live.
  useEffect(() => {
    if (!live) return undefined;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const poll = setInterval(async () => {
      try {
        setQr(await api.getPatientQR(qr.id));
      } catch {
        /* keep showing the code; next poll retries */
      }
    }, POLL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [live, qr?.id]);

  const toggleScope = (s) =>
    setScope((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));

  const generate = async () => {
    setBusy(true);
    setError('');
    try {
      const created = await api.createPatientQR(scope, accessDays, validMinutes);
      setToken(created.token);
      setShortCode(created.short_code || '');
      setQr(created);
      setNow(Date.now());
    } catch (err) {
      setError(err.detail || 'Could not create a QR code.');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    try {
      setQr(await api.revokePatientQR(qr.id));
    } catch (err) {
      setError(err.detail || 'Could not cancel the QR code.');
    }
  };

  const qrValue = token ? `${window.location.origin}/add-patient/${token}` : '';

  return (
    <div>
      <div className="page-header">
        <h1>My QR code</h1>
        <p>
          Show this code to your doctor. When they scan it in MediPass you're added to their patient list
          straight away, sharing only what you choose below. You can revoke their access anytime.
        </p>
      </div>

      <div className="surface" style={{ maxWidth: 620, marginBottom: '1.5rem' }}>
        <div className="field">
          <label>What should the doctor be able to see?</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {SCOPE_OPTIONS.map((s) => (
              <button
                key={s}
                type="button"
                className={`scope-chip ${scope.includes(s) ? 'selected' : ''}`}
                onClick={() => toggleScope(s)}
              >
                {s.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
          <div className="field">
            <label htmlFor="qr-access">Doctor keeps access for</label>
            <select id="qr-access" value={accessDays} onChange={(e) => setAccessDays(Number(e.target.value))}>
              {ACCESS_OPTIONS.map((d) => <option key={d} value={d}>{d} days</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="qr-valid">Code can be scanned for</label>
            <select id="qr-valid" value={validMinutes} onChange={(e) => setValidMinutes(Number(e.target.value))}>
              {VALIDITY_OPTIONS.map((o) => <option key={o.minutes} value={o.minutes}>{o.label}</option>)}
            </select>
          </div>
        </div>

        {error && <p className="error-text">{error}</p>}

        <button className="btn btn-primary" onClick={generate} disabled={busy || scope.length === 0}>
          {qr ? 'Generate a new code' : 'Generate my QR code'}
        </button>
        <p className="muted" style={{ fontSize: '0.8rem', margin: '0.6rem 0 0' }}>
          Each code works once. Generating a new code cancels any unused one.
        </p>
      </div>

      {qr && (
        <div className="surface qr-card" style={{ maxWidth: 620 }}>
          {live && (
            <>
              <div>
                {shortCode && (
                  <div className="qr-short-code">
                    <span className="muted">Code</span>
                    <strong className="mono" aria-label="Patient code">{shortCode}</strong>
                  </div>
                )}
                <div className="qr-box">
                  <QRCode value={qrValue} size={220} />
                </div>
              </div>
              <div>
                <h3 style={{ margin: '0 0 0.4rem' }}>Ready to scan</h3>
                <p className="muted" style={{ fontSize: '0.88rem', margin: '0 0 0.4rem' }}>
                  Shares: <strong>{qr.scope.join(', ').replace('_', ' ')}</strong> for {qr.access_days} days.
                </p>
                <p className="mono" style={{ fontSize: '0.88rem', margin: '0 0 0.8rem' }}>
                  Expires in {formatRemaining(expiresAt - now)}
                </p>
                <p className="muted" style={{ fontSize: '0.8rem', margin: '0 0 0.8rem' }}>
                  Doctor's camera not working? They can type the code <strong className="mono">{shortCode}</strong>
                  {' '}under <strong>Scan patient QR</strong> instead. It works once, like the QR.
                </p>
                <button className="btn btn-danger btn-sm" onClick={cancel}>Cancel this code</button>
              </div>
            </>
          )}
          {qr.used_at && qr.outcome === 'already_patient' && (
            <p className="qr-status ok">
              ✓ {qr.used_by_name || 'Your doctor'} scanned your code. You're already their patient, so nothing
              changed. Manage their access in <strong>Access requests</strong>.
            </p>
          )}
          {qr.used_at && qr.outcome !== 'already_patient' && (
            <p className="qr-status ok">
              ✓ {qr.used_by_name || 'Your doctor'} scanned your code and has been added. Manage their access in
              {' '}<strong>Access requests</strong>.
            </p>
          )}
          {!qr.used_at && qr.revoked && <p className="qr-status">This code was cancelled.</p>}
          {!qr.used_at && !qr.revoked && expiresAt <= now && (
            <p className="qr-status">This code expired before it was scanned. Generate a new one.</p>
          )}
        </div>
      )}
    </div>
  );
}
