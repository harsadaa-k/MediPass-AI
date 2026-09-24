import ActivePatients from './ActivePatients';

/** Sidebar page: the doctor's Active Patients list on its own. */
export default function ActivePatientsPage({ onOpenPatient }) {
  return (
    <div>
      <div className="page-header">
        <h1>Active patients</h1>
        <p>Everyone you currently have access to, with their status, last visit and follow-ups.</p>
      </div>
      <ActivePatients onOpenPatient={(id, name) => onOpenPatient({ id, name })} />
    </div>
  );
}
