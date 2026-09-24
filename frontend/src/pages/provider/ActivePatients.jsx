import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api';
import { parseUtc } from '../../grants';
import { daysBetween, formatDay, plural, relativeDays, todayISO } from '../../dates';

const REFRESH_MS = 60_000;

const STATUS = {
  critical: { label: 'Critical', rank: 0 },
  follow_up: { label: 'Follow-up required', rank: 1 },
  new: { label: 'New', rank: 2 },
  ongoing: { label: 'Ongoing', rank: 3 },
};
const FILTERS = ['all', 'critical', 'follow_up', 'new', 'ongoing'];

const SORTS = {
  status: { label: 'Status (most urgent first)', fn: (a, b) => STATUS[a.status].rank - STATUS[b.status].rank || byName(a, b) },
  name: { label: 'Name (A–Z)', fn: (a, b) => byName(a, b) },
  last_visit: {
    label: 'Longest since last visit',
    fn: (a, b) => (b.days_since_last_visit ?? Infinity) - (a.days_since_last_visit ?? Infinity) || byName(a, b),
  },
  under_care: { label: 'Longest under your care', fn: (a, b) => b.days_under_care - a.days_under_care || byName(a, b) },
  expiry: {
    label: 'Access ending soonest',
    fn: (a, b) => (a.days_until_access_expires ?? Infinity) - (b.days_until_access_expires ?? Infinity) || byName(a, b),
  },
};

function byName(a, b) {
  return (a.patient_name || '').localeCompare(b.patient_name || '');
}

function FollowUp({ due }) {
  if (!due) return <span className="muted">None set</span>;
  const n = daysBetween(todayISO(), due);
  const cls = n < 0 ? 'ap-overdue' : n === 0 ? 'ap-due' : '';
  return (
    <span className={cls} title={formatDay(due)}>
      {n < 0 ? `Overdue by ${plural(-n, 'day')}` : n === 0 ? 'Due today' : `Due ${relativeDays(n)}`}
    </span>
  );
}

/**
 * The doctor's Active Patients section: count with last-updated time,
 * status per patient (critical / follow-up required / new / ongoing, see
 * backend routers/provider_patients.py), filter, search, sort, and the
 * inactive (expired or revoked) patients kept apart underneath.
 */
export default function ActivePatients({ onOpenPatient, highlightPatientId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('status');
  const [query, setQuery] = useState('');
  const [savingId, setSavingId] = useState(null);

  const load = useCallback(() => api.getProviderPatients()
    .then((d) => { setData(d); setError(''); })
    .catch((err) => setError(err.detail || 'Could not load your patients.')), []);

  const refresh = async () => {
    setLoading(true);
    await load();
    setLoading(false);
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    return data.active
      .filter((p) => filter === 'all' || p.status === filter)
      .filter((p) => !q || `${p.patient_name} ${p.patient_email}`.toLowerCase().includes(q))
      .sort(SORTS[sort].fn);
  }, [data, filter, sort, query]);

  const changeStatus = async (patient, value) => {
    setSavingId(patient.patient_id);
    try {
      await api.setPatientStatus(patient.patient_id, value === 'auto' ? null : value);
      await load();
    } catch (err) {
      setError(err.detail || 'Could not change the status.');
    } finally {
      setSavingId(null);
    }
  };

  if (!data) {
    return (
      <section className="active-patients">
        <h2>Active patients</h2>
        {error ? <p className="error-text">{error}</p> : <p className="muted">Loading patients…</p>}
      </section>
    );
  }

  const updated = parseUtc(data.generated_at);

  return (
    <section className="active-patients" aria-labelledby="active-patients-title">
      <header className="ap-header">
        <div>
          <h2 id="active-patients-title">
            Active patients <span className="ap-count">{data.total_active}</span>
          </h2>
          <div className="ap-updated">
            Last updated {updated?.toLocaleTimeString()} · refreshes every minute
          </div>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={refresh} disabled={loading}>
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </header>

      <div className="ap-filters" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            className={`ap-filter ${f !== 'all' ? `status-${f}` : ''} ${filter === f ? 'selected' : ''}`}
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? 'All' : STATUS[f].label}
            <span className="ap-filter-count">{f === 'all' ? data.total_active : data.counts[f]}</span>
          </button>
        ))}
      </div>

      <div className="ap-toolbar">
        <input
          type="search"
          placeholder="Search by name or email"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search patients"
        />
        <label className="ap-sort">
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {Object.entries(SORTS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="error-text">{error}</p>}

      {data.total_active === 0 ? (
        <p className="muted ap-empty">No patients with active access. Scan a patient's QR code or request access to add one.</p>
      ) : rows.length === 0 ? (
        <p className="muted ap-empty">No patients match this filter.</p>
      ) : (
        <ul className="ap-list">
          {rows.map((p) => (
            <li
              key={p.patient_id}
              className={`ap-row status-${p.status} ${highlightPatientId === p.patient_id ? 'just-added' : ''}`}
            >
              <div className="ap-main">
                <div className="ap-name">{p.patient_name}</div>
                <div className="ap-sub">{p.patient_email}</div>
                <div className="ap-sub">Sharing: {p.scope.length ? p.scope.join(', ').replace('_', ' ') : 'nothing'}</div>
              </div>

              <div className="ap-status">
                <span className={`status-pill status-${p.status}`}>{STATUS[p.status].label}</span>
                <div className="ap-reason" title={p.status_reason}>{p.status_reason}</div>
              </div>

              <dl className="ap-metrics">
                <div>
                  <dt>Under your care</dt>
                  <dd title={`Since ${formatDay(parseUtc(p.granted_at))}`}>{plural(p.days_under_care, 'day')}</dd>
                </div>
                <div>
                  <dt>Last visit</dt>
                  <dd>
                    {p.last_visit
                      ? <span title={formatDay(p.last_visit)}>{relativeDays(-p.days_since_last_visit)}</span>
                      : <span className="muted">No visit yet</span>}
                  </dd>
                </div>
                <div>
                  <dt>Follow-up</dt>
                  <dd><FollowUp due={p.follow_up_due} /></dd>
                </div>
                <div>
                  <dt>Access</dt>
                  <dd className={p.days_until_access_expires != null && p.days_until_access_expires <= 3 ? 'ap-due' : ''}>
                    {p.days_until_access_expires == null
                      ? 'No end date'
                      : p.days_until_access_expires <= 0 ? 'Ends today' : `${plural(p.days_until_access_expires, 'day')} left`}
                  </dd>
                </div>
                <div>
                  <dt>Records</dt>
                  <dd>{p.records_shared} shared · {plural(p.consultations, 'note')} by you</dd>
                </div>
              </dl>

              <div className="ap-actions">
                <button className="btn btn-primary btn-sm" onClick={() => onOpenPatient(p.patient_id, p.patient_name)}>
                  View patient
                </button>
                <select
                  aria-label={`Status for ${p.patient_name}`}
                  value={p.status_set_by_doctor ? p.status : 'auto'}
                  disabled={savingId === p.patient_id}
                  onChange={(e) => changeStatus(p, e.target.value)}
                >
                  <option value="auto">Status: automatic</option>
                  {Object.entries(STATUS).map(([k, s]) => <option key={k} value={k}>Mark: {s.label}</option>)}
                </select>
              </div>
            </li>
          ))}
        </ul>
      )}

      {data.inactive.length > 0 && (
        <details className="ap-inactive">
          <summary>Inactive patients ({data.inactive.length}) — access expired or revoked</summary>
          <ul>
            {data.inactive.map((p) => (
              <li key={p.patient_id}>
                <span className="ap-name">{p.patient_name}</span>
                <span className="ap-sub">
                  {p.patient_email} ·{' '}
                  {p.reason === 'expired'
                    ? `access expired ${formatDay(parseUtc(p.expired_at))}`
                    : 'access revoked by the patient'}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
