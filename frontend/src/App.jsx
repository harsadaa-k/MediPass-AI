import { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';

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

function Root() {
  const { user, loading } = useAuth();

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
