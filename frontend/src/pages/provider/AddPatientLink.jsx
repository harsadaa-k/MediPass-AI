import { Navigate, useParams } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import { savePendingQr } from '../../pendingQr';

/**
 * /add-patient/:token -- what the QR code encodes, so a phone's own camera
 * app also works. The token is parked in sessionStorage and the provider
 * dashboard redeems it (after login, if needed) and shows the result.
 */
export default function AddPatientLink() {
  const { token } = useParams();
  const { user } = useAuth();

  if (user?.role === 'patient') {
    return (
      <div className="auth-screen" style={{ padding: '2rem' }}>
        <p>This QR code is for your doctor to scan from their MediPass account.</p>
        <a href="/">Back to MediPass</a>
      </div>
    );
  }

  // Saved during render (idempotent) so it's stored before <Navigate> redirects.
  if (token) savePendingQr(token);
  return <Navigate to="/" replace />;
}
