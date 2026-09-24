import { useEffect, useRef, useState } from 'react';
import Timeline from '../../components/Timeline';
import AddConsultationForm from './AddConsultationForm';
import AiSummaryPanel from '../../components/AiSummaryPanel';
import { parseUtc } from '../../grants';

export default function PatientViewPage({
  patient, onBack, focusConsultation = false, backLabel = 'my requests', notice = null, onDismissNotice,
}) {
  const [refreshKey, setRefreshKey] = useState(0);
  const formRef = useRef(null);

  // "Add Consultation" quick action from the dashboard jumps straight to the form.
  // The summary and timeline above it load asynchronously and push it down,
  // so re-scroll a few times while they settle (stop if the user scrolls).
  useEffect(() => {
    if (!focusConsultation) return undefined;
    let userScrolled = false;
    const stop = () => { userScrolled = true; };
    window.addEventListener('wheel', stop, { passive: true });
    window.addEventListener('touchmove', stop, { passive: true });
    const timers = [0, 400, 1000, 2000, 3500].map((ms) =>
      setTimeout(() => {
        if (!userScrolled && formRef.current) {
          // smooth scrolling doesn't run in background tabs, so jump instead there
          const smooth = ms > 0 && !document.hidden;
          formRef.current.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
        }
      }, ms)
    );
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener('wheel', stop);
      window.removeEventListener('touchmove', stop);
    };
  }, [focusConsultation]);

  if (!patient) {
    return (
      <div className="empty-state">
        No patient selected. Open one from "My requests" first.
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <button className="btn btn-secondary btn-sm" onClick={onBack} style={{ marginBottom: '0.9rem' }}>
          ← Back to {backLabel}
        </button>
        <h1>{patient.name}</h1>
        <p>Viewing the history this patient has shared with you.</p>
      </div>

      {notice?.kind === 'existing' && (
        <div className="qr-existing-banner" role="status">
          <div>
            <strong>ℹ {patient.name} is already your patient</strong>
            <div style={{ fontSize: '0.85rem' }}>
              Their QR code didn't change anything — you already have access
              {notice.scope?.length ? ` to ${notice.scope.join(', ').replace('_', ' ')}` : ''}
              {notice.expires_at ? ` until ${parseUtc(notice.expires_at).toLocaleDateString()}` : ''}.
              Opened their profile.
            </div>
          </div>
          {onDismissNotice && (
            <button className="btn btn-secondary btn-sm" onClick={onDismissNotice}>Dismiss</button>
          )}
        </div>
      )}

      <AiSummaryPanel patientId={patient.id} refreshKey={refreshKey} />

      <div className="section">
        <h2>Timeline</h2>
        <Timeline patientId={patient.id} refreshKey={refreshKey} />
      </div>

      <div className="section" ref={formRef}>
        <AddConsultationForm patientId={patient.id} onAdded={() => setRefreshKey((k) => k + 1)} />
      </div>
    </div>
  );
}
