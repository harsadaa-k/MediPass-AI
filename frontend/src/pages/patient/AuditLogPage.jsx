import { useEffect, useState } from 'react';
import { api } from '../../api';
import { parseUtc } from '../../grants';

// Doctors are shown as "Dr. <name>"; the patient's own actions as "You".
const who = (e) => {
  if (e.actor_role === 'patient') return 'You';
  const n = (e.actor_name || '').trim();
  if (!n) return 'A doctor';
  return /^dr\b/i.test(n) ? n : `Dr. ${n}`;
};

const ACTION_LABEL = {
  access_requested: (e) => `${who(e)} requested access to your records`,
  access_approved: () => 'You approved an access request',
  access_denied: () => 'You denied an access request',
  access_revoked: () => 'You revoked a doctor\'s access',
  access_auto_revoked: (e) => `${who(e)}'s access expired`,
  record_added: (e) => `${who(e)} added a new record`,
  emergency_access_viewed: () => 'Your emergency link was opened',
  qr_code_created: () => 'You created a QR code for a doctor',
  access_granted_via_qr: (e) => `${who(e)} added you by scanning your QR code`,
  qr_scanned_existing_patient: (e) => `${who(e)} scanned your QR code (already your doctor, nothing changed)`,
  record_linked: (e) => `A consultation note by ${who(e)} was linked to a prescription`,
  record_link_needs_review: (e) => `A consultation note by ${who(e)} matches more than one prescription`,
  record_link_overridden: (e) => `${who(e)} changed which prescription a consultation note is linked to`,
  record_link_confirmed: () => 'You confirmed a consultation note ↔ prescription link',
  record_link_rejected: () => 'You rejected a proposed consultation note ↔ prescription link',
  prescriber_edited: () => 'You updated the doctor / hospital on a prescription',
  duplicate_record_removed: () => 'A duplicate record (same prescription uploaded twice) was removed',
};

export default function AuditLogPage() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const data = await api.getAuditLog();
        setLogs(data);
      } catch (err) {
        setError(err.detail || 'Could not load your activity log.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div>
      <div className="page-header">
        <h1>Activity log</h1>
        <p>Every access request, approval, and record added to your history.</p>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && (
        logs.length === 0 ? (
          <div className="empty-state">No activity yet.</div>
        ) : (
          <div className="timeline-list">
            {logs.map((entry) => (
              <div key={entry.id} className="list-row">
                <div className="row-main">
                  <div className="row-title">{ACTION_LABEL[entry.action]?.(entry) || entry.action}</div>
                  <div className="row-sub mono">{parseUtc(entry.timestamp).toLocaleString()}</div>
                </div>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
