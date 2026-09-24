import { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { api } from '../api';
import Sidebar from '../components/Sidebar';
import PatientOverview from './patient/PatientOverview';
import UploadDocument from './patient/UploadDocument';
import VerifyQueue from './patient/VerifyQueue';
import PatientTimelinePage from './patient/PatientTimelinePage';
import AccessRequestsPage from './patient/AccessRequestsPage';
import MyQRCodePage from './patient/MyQRCodePage';
import AuditLogPage from './patient/AuditLogPage';
import MedicationsPage from './patient/MedicationsPage';
import LabResultsPage from './patient/LabResultsPage';
import NotificationsPage from './patient/NotificationsPage';

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'timeline', label: 'Your timeline' },
  { key: 'medications', label: 'Medications' },
  { key: 'lab_results', label: 'Lab results' },
  { key: 'upload', label: 'Upload a document' },
  { key: 'verify', label: 'Verify records' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'access', label: 'Access requests' },
  { key: 'myqr', label: 'My QR code' },
  { key: 'audit', label: 'Activity log' },
];

export default function PatientDashboard() {
  const { user, logout } = useAuth();
  const [active, setActive] = useState('dashboard');
  const [timelineRefreshKey, setTimelineRefreshKey] = useState(0);
  const [badges, setBadges] = useState({});

  const loadBadges = async () => {
    if (!user) return; // token may not be set yet
    try {
      const data = await api.getBadges();
      setBadges({
        access: data.pending_access_requests,
        verify: data.unverified_records + (data.pending_links || 0),
        notifications: data.unread_notifications,
      });
    } catch (err) {
      // Silently ignore 401s — they happen during token refresh / race
      if (err?.status === 401) return;
      console.error('Could not load badges:', err);
    }
  };

  useEffect(() => {
    loadBadges();
    const interval = setInterval(loadBadges, 30000);
    return () => clearInterval(interval);
  }, [user]); // re-run when user changes (login/logout)

  const bumpTimeline = () => {
    setTimelineRefreshKey((k) => k + 1);
    loadBadges(); // Refresh badges immediately when user acts
  };

  return (
    <div className="app-shell">
      <Sidebar
        items={NAV_ITEMS}
        active={active}
        onSelect={setActive}
        userName={user.full_name}
        roleLabel="Patient"
        onLogout={logout}
        badges={badges}
      />
      <main className="main">
        {active === 'dashboard' && <PatientOverview onNavigate={setActive} />}
        {active === 'timeline' && <PatientTimelinePage refreshKey={timelineRefreshKey} />}
        {active === 'medications' && <MedicationsPage />}
        {active === 'lab_results' && <LabResultsPage />}
        {active === 'upload' && <UploadDocument onUploaded={bumpTimeline} />}
        {active === 'verify' && <VerifyQueue onVerified={bumpTimeline} />}
        {active === 'notifications' && <NotificationsPage onAction={loadBadges} />}
        {active === 'access' && <AccessRequestsPage onAction={loadBadges} />}
        {active === 'myqr' && <MyQRCodePage />}
        {active === 'audit' && <AuditLogPage />}
      </main>
    </div>
  );
}
