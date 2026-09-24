import { useAuth } from '../../AuthContext';
import Timeline from '../../components/Timeline';

export default function PatientTimelinePage({ refreshKey }) {
  const { user } = useAuth();
  return (
    <div>
      <div className="page-header">
        <h1>Your timeline</h1>
        <p>Everything you've verified and everything your doctors have added, in one place.</p>
      </div>
      <Timeline patientId={user.id} refreshKey={refreshKey} />
    </div>
  );
}
