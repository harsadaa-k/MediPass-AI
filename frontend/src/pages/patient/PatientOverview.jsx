import { useEffect, useState } from 'react';
import { useAuth } from '../../AuthContext';
import { api } from '../../api';
import { isActiveGrant } from '../../grants';
import { daysSince, todayISO } from '../../dates';

const RECENT_DAYS = 30;
const ACTIVE_MED_DAYS = 90;

// Whole calendar days since a record date (timezone-safe, see dates.js)
function daysAgo(dateStr, now) {
  return daysSince(dateStr, now);
}

export default function PatientOverview({ onNavigate }) {
  const { user } = useAuth();
  const [badges, setBadges] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [grants, setGrants] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [b, t, g] = await Promise.all([
          api.getBadges(),
          api.getTimeline(user.id),
          api.listMyGrantsAsPatient(),
        ]);
        setBadges(b);
        setTimeline(t);
        setGrants(g);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      } finally {
        setLoading(false);
      }
    })();
  }, [user.id]);

  if (loading) return <p className="muted">Loading dashboard…</p>;

  const now = new Date();
  const records = timeline?.records || [];
  const recentEvents = records.filter((r) => daysAgo(r.record_date, now) <= RECENT_DAYS).length;

  // "Active" = distinct medicines still being taken (the same drug prescribed
  // twice counts once): a course with a written duration counts until its end
  // date; without one, medicines recorded in the last ACTIVE_MED_DAYS days.
  const today = todayISO(now);
  const isActiveMed = (r) => {
    if (r.course?.end_date) return r.course.end_date >= today && r.course.start_date <= today;
    return daysAgo(r.record_date, now) <= ACTIVE_MED_DAYS;
  };
  const activeMeds = new Set(
    records
      .filter((r) => r.record_type === 'medication' && isActiveMed(r))
      .map((r) => (r.details?.medicine || r.title).trim().toLowerCase())
  ).size;

  const activeGrants = grants.filter((g) => isActiveGrant(g, now));
  const activeSharing = activeGrants.length;

  const stats = [
    { label: `Timeline events (last ${RECENT_DAYS}d)`, value: recentEvents, color: '#6366f1', tab: 'timeline' },
    { label: 'Active medications', title: `Courses that haven't ended; medicines without a written duration count for ${ACTIVE_MED_DAYS} days`, value: activeMeds, color: '#10b981', tab: 'medications' },
    { label: 'Pending verifications', value: badges?.unverified_records ?? 0, color: '#f59e0b', tab: 'verify' },
    { label: 'Pending access requests', value: badges?.pending_access_requests ?? 0, color: '#ef4444', tab: 'access' },
    { label: 'Active sharing sessions', value: activeSharing, color: '#0e8a8c', tab: 'access' },
    { label: 'Unread notifications', value: badges?.unread_notifications ?? 0, color: '#8b5cf6', tab: 'notifications' },
  ];

  return (
    <div>
      <div className="page-header">
        <h1>Welcome back, {user.full_name.split(' ')[0]}!</h1>
        <p>Here's a quick snapshot of your MediPass health record.</p>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: '1rem',
        marginBottom: '1.5rem',
      }}>
        {stats.map((s) => (
          <button
            key={s.label}
            type="button"
            title={s.title}
            className="surface"
            onClick={() => onNavigate && onNavigate(s.tab)}
            style={{
              textAlign: 'center',
              padding: '1.25rem 1rem',
              borderTop: `3px solid ${s.color}`,
              cursor: onNavigate ? 'pointer' : 'default',
              font: 'inherit',
            }}
          >
            <div style={{ fontSize: '2rem', fontWeight: 700, color: s.color }}>{s.value}</div>
            <div className="muted" style={{ fontSize: '0.85rem', marginTop: '0.3rem' }}>{s.label}</div>
          </button>
        ))}
      </div>

      {activeSharing > 0 && (
        <div className="surface" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ marginBottom: '0.75rem' }}>Who can see your records</h3>
          {activeGrants.map((g) => (
            <div key={g.id} className="list-row" style={{ padding: '0.6rem 0', borderBottom: '1px solid var(--border)' }}>
              <div className="row-main">
                <div className="row-title">
                  {g.provider_name}
                  {g.provider_verified
                    ? <span className="badge badge-green" style={{ marginLeft: '0.5rem' }}>✓ Verified doctor</span>
                    : <span className="badge badge-amber" style={{ marginLeft: '0.5rem' }}>Not verified</span>}
                </div>
                <div className="row-sub">
                  {g.provider_specialty ? `${g.provider_specialty} · ` : ''}
                  sharing: {g.scope?.length ? g.scope.join(', ') : 'nothing'}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {records.length > 0 && (
        <div className="surface">
          <h3 style={{ marginBottom: '0.75rem' }}>Recent timeline entries</h3>
          {records.slice(-5).reverse().map((r) => (
            <div
              key={r.id}
              className="list-row"
              style={{ padding: '0.6rem 0', borderBottom: '1px solid var(--border)' }}
            >
              <div className="row-main">
                <div className="row-title">{r.title}</div>
                <div className="row-sub">
                  {r.record_type.replace('_', ' ')} · {r.record_date}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
