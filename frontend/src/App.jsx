import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import SplashScreen from './components/SplashScreen';

// Each role's screens load on demand, so a patient never downloads the
// doctor's screens (and vice versa) and the first load stays small.
const AuthPage = lazy(() => import('./pages/AuthPage'));
const VerifyEmailPage = lazy(() => import('./pages/auth/VerifyEmailPage'));
const ResetPasswordPage = lazy(() => import('./pages/auth/ResetPasswordPage'));
const PatientDashboard = lazy(() => import('./pages/PatientDashboard'));
const ProviderDashboard = lazy(() => import('./pages/ProviderDashboard'));
const AddPatientLink = lazy(() => import('./pages/provider/AddPatientLink'));
const ReviewDecisionPage = lazy(() => import('./pages/ReviewDecisionPage'));

function Loading() {
  return (
    <div className="auth-screen" style={{ padding: '2rem' }}>
      <p className="muted">Loading MediPass...</p>
    </div>
  );
}

const SPLASH_SEEN = 'medipass_splash_seen';

// The intro screen plays when the app is opened at its main link, once per
// browser tab (not on refreshes, deep links such as email or QR links, or
// after sign-out).
function shouldShowSplash(pathname) {
  if (pathname !== '/') return false;
  try {
    return !sessionStorage.getItem(SPLASH_SEEN);
  } catch {
    return true;
  }
}

function Root() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [splash, setSplash] = useState(() => shouldShowSplash(location.pathname));

  // Fetch the login screen while the intro plays, so it appears instantly.
  useEffect(() => {
    if (splash) import('./pages/AuthPage');
  }, [splash]);

  const finishSplash = useCallback(() => {
    try {
      sessionStorage.setItem(SPLASH_SEEN, '1');
    } catch {
      /* private mode: the intro just plays again next time */
    }
    setSplash(false);
    if (!user) navigate('/login', { replace: true });
  }, [user, navigate]);

  if (splash) return <SplashScreen onDone={finishSplash} />;
  if (loading) return <Loading />;

  return (
    <Suspense fallback={<Loading />}>
    <Routes>
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/add-patient/:token" element={<AddPatientLink />} />
      <Route path="/review-decision" element={<ReviewDecisionPage />} />
      <Route
        path="/*"
        element={
          !user ? (
            <AuthPage />
          ) : user.role === 'patient' ? (
            <PatientDashboard />
          ) : (
            <ProviderDashboard />
          )
        }
      />
    </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Router>
        <Root />
      </Router>
    </AuthProvider>
  );
}
