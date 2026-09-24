import { useEffect, useState } from 'react';
import { api } from '../../api';
import { parseUtc } from '../../grants';

export default function NotificationsPage({ onAction }) {
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.getNotifications();
      setNotifications(data);
    } catch (err) {
      setError(err.detail || 'Could not load notifications.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const markRead = async (id) => {
    try {
      await api.markNotificationRead(id);
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
      if (onAction) onAction();
    } catch (err) {
      console.error('Failed to mark notification read:', err);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Notifications</h1>
        <p>Updates from your doctors and system alerts.</p>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && notifications.length === 0 && (
        <div className="empty-state">No notifications yet.</div>
      )}

      {notifications.map((n) => (
        <div
          key={n.id}
          className="list-row"
          style={{
            opacity: n.is_read ? 0.6 : 1,
            borderLeft: n.is_read ? '3px solid transparent' : '3px solid var(--brand)',
          }}
        >
          <div className="row-main">
            <div className="row-title">{n.message}</div>
            <div className="row-sub">
              {parseUtc(n.created_at).toLocaleString()}
            </div>
          </div>
          <div className="row-actions">
            {!n.is_read && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => markRead(n.id)}
              >
                Mark read
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
