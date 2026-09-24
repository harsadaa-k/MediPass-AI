import { lazy, Suspense, useEffect, useState } from 'react';
import { useAuth } from '../AuthContext';
import { api } from '../api';
import { takePendingQr } from '../pendingQr';
import Sidebar from '../components/Sidebar';
import ProviderOverview from './provider/ProviderOverview';
import FindPatientPage from './provider/FindPatientPage';
import MyRequestsPage from './provider/MyRequestsPage';
import PatientViewPage from './provider/PatientViewPage';
import ProviderProfilePage from './provider/ProviderProfilePage';
import ActivePatientsPage from './provider/ActivePatientsPage';

// Loaded on demand: the QR decoder is only needed when a doctor scans.
const ScanPatientQRPage = lazy(() => import('./provider/ScanPatientQRPage'));

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'scan', label: 'Scan patient QR' },
  { key: 'patients', label: 'Active patients' },
  { key: 'find', label: 'Find a patient' },
  { key: 'requests', label: 'My requests' },
  { key: 'profile', label: 'My Profile' },
];

export default function ProviderDashboard() {
  const { user, logout } = useAuth();
  const [active, setActive] = useState('dashboard');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [focusConsultation, setFocusConsultation] = useState(false);
  const [returnTo, setReturnTo] = useState('requests');
  const [requestsRefreshKey, setRequestsRefreshKey] = useState(0);
  const [justAdded, setJustAdded] = useState(null); // result of the last QR scan
  const [qrLinkError, setQrLinkError] = useState('');
  const [patientNotice, setPatientNotice] = useState(null); // shown on the opened profile

  const openPatient = (patient, { focusConsultation: focus = false, notice = null } = {}) => {
    setSelectedPatient(patient);
    setFocusConsultation(focus);
    setPatientNotice(notice);
    setReturnTo(active === 'patient' ? returnTo : active);
    setActive('patient');
  };

  // Patient scanned in. New patient: show them on the dashboard. Already an
  // active patient: nothing changed, so open their profile and say so.
  const handleAdded = (result) => {
    setQrLinkError('');
    setRequestsRefreshKey((k) => k + 1);
    if (result.already_had_access) {
      setJustAdded(null);
      openPatient(
        { id: result.patient_id, name: result.patient_name },
        { notice: { kind: 'existing', ...result } }
      );
      return;
    }
    setJustAdded(result);
    setActive('dashboard');
  };

  // A QR link opened with the phone/browser camera (/add-patient/<token>).
  useEffect(() => {
    const token = takePendingQr();
    if (!token) return;
    api.redeemPatientQR(token)
      .then(handleAdded)
      .catch((err) => setQrLinkError(err.detail || 'That patient QR code could not be used.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = selectedPatient
    ? [...NAV_ITEMS, { key: 'patient', label: selectedPatient.name }]
    : NAV_ITEMS;

  return (
    <div className="app-shell">
      <Sidebar
        items={items}
        active={active}
        onSelect={setActive}
        userName={user.full_name}
        roleLabel="Doctor"
        onLogout={logout}
      />
      <main className="main">
        {active === 'dashboard' && (
          <ProviderOverview
            onNavigate={setActive}
            onOpenPatient={openPatient}
            justAdded={justAdded}
            onDismissJustAdded={() => setJustAdded(null)}
            qrLinkError={qrLinkError}
          />
        )}
        {active === 'scan' && (
          <Suspense fallback={<p className="muted">Loading scanner…</p>}>
            <ScanPatientQRPage onAdded={handleAdded} />
          </Suspense>
        )}
        {active === 'find' && (
          <FindPatientPage onRequested={() => setRequestsRefreshKey((k) => k + 1)} />
        )}
        {active === 'requests' && (
          <MyRequestsPage onOpenPatient={openPatient} refreshKey={requestsRefreshKey} />
        )}
        {active === 'patient' && (
          <PatientViewPage
            key={selectedPatient?.id}
            patient={selectedPatient}
            focusConsultation={focusConsultation}
            notice={patientNotice}
            onDismissNotice={() => setPatientNotice(null)}
            backLabel={{ dashboard: 'dashboard', patients: 'active patients' }[returnTo] || 'my requests'}
            onBack={() => setActive(returnTo)}
          />
        )}
        {active === 'patients' && <ActivePatientsPage onOpenPatient={openPatient} />}
        {active === 'profile' && <ProviderProfilePage />}
      </main>
    </div>
  );
}
