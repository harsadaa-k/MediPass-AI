import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../AuthContext';
import { api } from '../../api';
import TimelineRecord from '../../components/TimelineRecord';
import RecordSortSelect from '../../components/RecordSortSelect';
import { readSavedSort, saveSort, sortRecords } from '../../recordSort';

export default function LabResultsPage() {
  const { user } = useAuth();
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sort, setSort] = useState(() => { const s = readSavedSort('date_asc'); return s === 'type' ? 'date_asc' : s; });
  const sorted = useMemo(() => sortRecords(records, sort), [records, sort]);
  const changeSort = (value) => {
    setSort(value);
    saveSort(value);
  };

  useEffect(() => {
    (async () => {
      try {
        const data = await api.getTimeline(user.id);
        setRecords(data.records.filter((r) => r.record_type === 'lab_result'));
      } catch (err) {
        setError(err.detail || 'Could not load lab results.');
      } finally {
        setLoading(false);
      }
    })();
  }, [user.id]);

  return (
    <div>
      <div className="page-header">
        <h1>Lab results</h1>
        <p>All lab-result records from your verified timeline.</p>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && records.length === 0 && (
        <div className="empty-state">No lab-result records found in your timeline yet.</div>
      )}

      {records.length > 1 && (
        <div className="timeline-toolbar">
          <RecordSortSelect value={sort} onChange={changeSort} exclude={['type']} />
        </div>
      )}

      {sorted.map((r) => (
        <TimelineRecord key={r.id} record={r} />
      ))}
    </div>
  );
}
