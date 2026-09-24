import { useEffect, useState } from 'react';
import { api } from '../api';
import ViewSourceButton from './ViewSourceButton';
import { parseUtc } from '../grants';
import { jumpTo } from '../scroll';

const docLabel = (d) =>
  `${d.doctor || 'Prescription'}${d.hospital ? ` (${d.hospital})` : ''}${d.date ? ` · ${d.date}` : ''}` +
  `${d.medicines?.length ? ` · ${d.medicines.slice(0, 3).join(', ')}` : ''}`;

// Scroll to the prescription's card; if the timeline filter hides it, ask
// the timeline to show everything first (Timeline listens for this event).
function showOnTimeline(docId) {
  if (!jumpTo(`doc-${docId}`)) {
    window.dispatchEvent(new CustomEvent('medipass:reveal', { detail: `doc-${docId}` }));
  }
}

/** What the linked prescription says: medicines with dose, timing and course. */
function PrescriptionContents({ doc }) {
  if (!doc.items?.length && !doc.diagnoses?.length) return null;
  return (
    <div className="linked-rx">
      <div className="linked-rx-head">
        💊 Prescription from <strong>{doc.doctor || 'the doctor'}</strong>
        {doc.hospital ? ` · ${doc.hospital}` : ''}{doc.date ? ` · ${doc.date}` : ''}
      </div>
      {doc.items?.length > 0 && (
        <ul className="linked-rx-list">
          {doc.items.map((m, i) => (
            <li key={i}>
              <span className="linked-rx-name">{m.name}</span>
              {[m.dose, m.timing, m.instructions, m.course].filter(Boolean).map((v, j) => (
                <span key={j} className="med-detail-chip">{v}</span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {doc.diagnoses?.length > 0 && (
        <div className="muted" style={{ fontSize: '0.82rem' }}>Diagnosis: {doc.diagnoses.join(', ')}</div>
      )}
    </div>
  );
}

/** The doctor's consultation (written from their account), shown with the prescription it belongs to. */
export function ConsultationContents({ note }) {
  const doctor = `Dr. ${(note.author_name || '').replace(/^dr\.?\s*/i, '')}`;
  const where = [note.author_specialty, note.author_hospital].filter(Boolean).join(', ');
  return (
    <div className="linked-rx">
      <div className="linked-rx-head">
        🩺 Consultation by <strong>{doctor}</strong>{where ? ` (${where})` : ''} · {note.date}
      </div>
      <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>{note.title}</div>
      {note.text && <p className="diagnosis-text">{note.text}</p>}
      {note.follow_up && <p className="diagnosis-text"><strong>Follow-up:</strong> {note.follow_up}</p>}
      {note.text === undefined && (
        <div className="muted" style={{ fontSize: '0.8rem' }}>The note's content isn't shared with you.</div>
      )}
    </div>
  );
}

/** Patient accepts (final) or rejects a proposed prescription link. */
export function LinkConfirmButtons({ link, onChanged }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const run = async (fn) => {
    setBusy(true);
    setError('');
    try {
      await fn();
      onChanged?.();
    } catch (err) {
      setError(err.detail || 'Could not save your answer.');
    } finally {
      setBusy(false);
    }
  };

  const accept = () => {
    if (!window.confirm('Confirm this link? Once confirmed it can\'t be changed or removed.')) return;
    run(() => api.acceptLink(link.id));
  };

  return (
    <div className="link-confirm-actions">
      {!rejecting ? (
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button className="btn btn-primary btn-sm" onClick={accept} disabled={busy}>✓ Yes, this is the right prescription</button>
          <button className="btn btn-secondary btn-sm" onClick={() => setRejecting(true)} disabled={busy}>No, wrong prescription</button>
        </div>
      ) : (
        <div>
          <div className="field" style={{ marginBottom: '0.5rem' }}>
            <label htmlFor={`rej-${link.id}`}>Why is it wrong? (optional)</label>
            <input id={`rej-${link.id}`} value={reason} onChange={(e) => setReason(e.target.value)}
                   placeholder="e.g. That visit was about something else" />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-danger btn-sm" onClick={() => run(() => api.rejectLink(link.id, reason))} disabled={busy}>
              Reject link
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setRejecting(false)}>Cancel</button>
          </div>
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

function OverrideEditor({ link, onDone, onCancel }) {
  const [candidates, setCandidates] = useState(null);
  const [choice, setChoice] = useState(link.document?.id || '');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api.getLinkCandidates(link.consultation.id)
      .then((c) => alive && setCandidates(c))
      .catch((err) => {
        if (!alive) return;
        setCandidates([]);
        setError(err.detail || 'Could not load prescriptions.');
      });
    return () => { alive = false; };
  }, [link.consultation.id]);

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      await api.overrideLink(link.consultation.id, choice || null, reason);
      onDone();
    } catch (err) {
      setError(err.detail || 'Could not save the change.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="link-editor">
      {candidates === null ? (
        <p className="muted">Loading prescriptions…</p>
      ) : (
        <div className="link-choices" role="radiogroup">
          {candidates.map((c) => (
            <label key={c.id} className={`link-choice ${c.eligible ? '' : 'dim'}`}>
              <input type="radio" name={`link-${link.id}`} checked={choice === c.id} onChange={() => setChoice(c.id)} />
              <span>
                <strong>{docLabel(c)}</strong>
                <span className="muted"> — {c.reason}{c.eligible ? ` (score ${Math.round(c.score * 100)})` : ''}</span>
              </span>
            </label>
          ))}
          <label className="link-choice">
            <input type="radio" name={`link-${link.id}`} checked={choice === ''} onChange={() => setChoice('')} />
            <span>No related prescription</span>
          </label>
        </div>
      )}
      <div className="field" style={{ marginTop: '0.6rem' }}>
        <label htmlFor={`reason-${link.id}`}>Reason for the change (kept in the record)</label>
        <input
          id={`reason-${link.id}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. This visit was about the June prescription"
        />
      </div>
      {error && <p className="error-text">{error}</p>}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving || reason.trim().length < 5}>
          Save link
        </button>
        <button className="btn btn-secondary btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/** "Related documents" on a doctor's consultation note. */
export function ConsultationLinkPanel({ link, canEdit, isPatient, onChanged }) {
  const [editing, setEditing] = useState(false);
  if (!link) return null;

  if (link.hidden) {
    return (
      <div className="related-docs">
        <span className="related-title">🔗 Related documents</span>
        <span className="muted">A linked prescription exists but the patient hasn't shared prescriptions with you.</span>
      </div>
    );
  }

  const byline = link.method === 'manual'
    ? `Linked manually by ${link.overridden_by || 'a user'} · “${link.override_reason}”`
    : `Linked automatically (${link.process}) · ${link.match_reason}`;

  return (
    <div className="related-docs">
      <span className="related-title">🔗 Related documents <span className="mono link-ref">{link.ref}</span></span>

      {(link.status === 'linked' || link.status === 'confirmed') && link.document && (
        <div className="related-row">
          <span>
            Prescription: <strong>{docLabel(link.document)}</strong>
            <span className="muted" title={parseUtc(link.updated_at)?.toLocaleString()}> — {byline}</span>
          </span>
          <PrescriptionContents doc={link.document} />
          <span className="related-actions">
            <button className="btn btn-secondary btn-sm" onClick={() => showOnTimeline(link.document.id)}>
              Show on timeline
            </button>
            <ViewSourceButton documentId={link.document.id} />
          </span>
        </div>
      )}

      {link.status === 'confirmed' && (
        <div className="related-row confirmed">
          ✓ Confirmed by the patient{link.confirmed_at ? ` on ${parseUtc(link.confirmed_at).toLocaleDateString()}` : ''} — this link is final
        </div>
      )}

      {link.status === 'linked' && (
        <div className="related-row warn">
          ⏳ Awaiting the patient's confirmation
        </div>
      )}
      {link.status === 'linked' && isPatient && <LinkConfirmButtons link={link} onChanged={onChanged} />}

      {link.status === 'ambiguous' && (
        <div className="related-row warn">
          ⚠ {link.match_reason}
          {link.candidates?.length > 0 && (
            <span className="muted"> Possible: {link.candidates.filter(Boolean).map(docLabel).join(' / ')}</span>
          )}
        </div>
      )}

      {link.status === 'unmatched' && (
        <div className="related-row muted">
          {link.method === 'manual' ? `No related prescription — ${byline}` : link.match_reason}
        </div>
      )}

      {canEdit && link.status !== 'confirmed' && !editing && (
        <button className="link-edit-btn" onClick={() => setEditing(true)}>
          {link.status === 'linked' ? 'Change link' : link.status === 'ambiguous' ? 'Choose prescription' : 'Link manually'}
        </button>
      )}
      {editing && (
        <OverrideEditor
          link={link}
          onCancel={() => setEditing(false)}
          onDone={() => { setEditing(false); onChanged?.(); }}
        />
      )}
    </div>
  );
}

/** Reverse direction: on a prescription, the consultation notes linked to it. */
export function PrescriptionLinkPanel({ links }) {
  if (!links?.length) return null;
  return (
    <div className="related-docs">
      <span className="related-title">🔗 Linked consultation{links.length > 1 ? 's' : ''}</span>
      {links.map((l) => (
        <div key={l.id} className="related-row">
          <ConsultationContents note={l.consultation} />
          <span className="muted" style={{ fontSize: '0.8rem' }}>
            <span className="mono">{l.ref}</span> · {l.method === 'manual' ? 'linked manually' : 'linked automatically'}
            {' '}· {l.status === 'confirmed' ? '✓ confirmed by patient' : 'awaiting patient confirmation'}
          </span>
          <button className="btn btn-secondary btn-sm" onClick={() => jumpTo(l.consultation.id)}>
            Go to note
          </button>
        </div>
      ))}
    </div>
  );
}
