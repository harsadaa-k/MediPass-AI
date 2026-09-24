import { useEffect, useState, useCallback } from 'react';
import { api } from '../api';
import { useAuth } from '../AuthContext';
import TimelineRecord from './TimelineRecord';
import GroupedRecordBox from './PrescriptionGroupRecord';
import FlagBanner from './FlagBanner';
import { ConsultationLinkPanel, PrescriptionLinkPanel } from './RelatedLinks';
import RecordSortSelect from './RecordSortSelect';
import { TYPE_LABELS, readSavedSort, saveSort, sortRecords } from '../recordSort';
import { jumpTo } from '../scroll';

/**
 * Groups AI-extracted records by category and source document:
 *  - All 'medication' records from the same source_document_id → one "Medicines" box
 *  - All 'diagnosis' records from the same source_document_id → one "Diagnosis" box
 *  - Everything else (allergy, consultation, lab_result, etc.) → individual entries
 */
function groupRecords(records) {
  const groups = [];
  // key = `${record_type}::${source_document_id}` → array of records
  const buckets = new Map();

  for (const record of records) {
    const isGroupable =
      record.source_type === 'ai_extracted' &&
      record.source_document_id &&
      (record.record_type === 'medication' || record.record_type === 'diagnosis');

    if (isGroupable) {
      const bucketKey = `${record.record_type}::${record.source_document_id}`;
      if (!buckets.has(bucketKey)) {
        buckets.set(bucketKey, []);
        // Push a placeholder to maintain chronological position
        groups.push({ type: 'group', bucketKey, recordType: record.record_type });
      }
      buckets.get(bucketKey).push(record);
    } else {
      groups.push({ type: 'single', record });
    }
  }

  // Replace placeholders with their accumulated records
  return groups.map((entry) => {
    if (entry.type === 'group') {
      return {
        type: 'group',
        groupType: entry.recordType === 'medication' ? 'medicines' : 'diagnosis',
        records: buckets.get(entry.bucketKey),
      };
    }
    return entry;
  });
}

export default function Timeline({ patientId, refreshKey }) {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [links, setLinks] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState(() => readSavedSort('date_asc'));
  const [typeFilter, setTypeFilter] = useState('all');

  // "Show on timeline" for a card the type filter hides: show all, then jump.
  const [pendingJump, setPendingJump] = useState(null);
  useEffect(() => {
    const reveal = (e) => { setTypeFilter('all'); setPendingJump(e.detail); };
    window.addEventListener('medipass:reveal', reveal);
    return () => window.removeEventListener('medipass:reveal', reveal);
  }, []);
  useEffect(() => {
    // runs after the re-render that shows the hidden card
    if (pendingJump && jumpTo(pendingJump)) setPendingJump(null);
  }, [pendingJump, typeFilter]);

  const changeSort = (value) => {
    setSort(value);
    saveSort(value);
  };

  const loadLinks = useCallback(async () => {
    try {
      setLinks(await api.getRecordLinks(patientId));
    } catch {
      setLinks([]); // links are extra context; the timeline still works without them
    }
  }, [patientId]);

  const load = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    setError('');
    try {
      const [result] = await Promise.all([api.getTimeline(patientId), loadLinks()]);
      setData(result);
    } catch (err) {
      setError(err.detail || 'Could not load the timeline.');
    } finally {
      setLoading(false);
    }
  }, [patientId, loadLinks]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading) return <p className="muted">Loading timeline…</p>;
  if (error) return <p className="error-text">{error}</p>;
  if (!data) return null;

  const presentTypes = [...new Set(data.records.map((r) => r.record_type))];
  const visible = data.records.filter((r) => typeFilter === 'all' || r.record_type === typeFilter);
  const grouped = groupRecords(sortRecords(visible, sort));

  // Link lookups for both directions
  const linkByNote = new Map(links.map((l) => [l.consultation?.id, l]));
  const linksByDoc = new Map();
  for (const l of links) {
    if ((l.status === 'linked' || l.status === 'confirmed') && l.document) {
      linksByDoc.set(l.document.id, [...(linksByDoc.get(l.document.id) || []), l]);
    }
  }
  const annotatedDocs = new Set(); // show the reverse link once per prescription
  const canEdit = (link) =>
    user?.role === 'patient' || (link?.consultation?.author_id && link.consultation.author_id === user?.id);

  return (
    <div>
      {data.flags.length > 0 && (
        <div className="section" style={{ marginBottom: '1rem' }}>
          {data.flags.map((flag, i) => (
            <FlagBanner key={i} flag={flag} />
          ))}
        </div>
      )}

      {data.records.length > 0 && (
        <div className="timeline-toolbar">
          <RecordSortSelect value={sort} onChange={changeSort} />
          <label>
            Show
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="all">All records ({data.records.length})</option>
              {presentTypes.map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t] || t} ({data.records.filter((r) => r.record_type === t).length})
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {grouped.length === 0 ? (
        <div className="empty-state">
          {data.records.length === 0
            ? 'No records on this timeline yet. Upload a document or wait for a doctor to add one.'
            : 'No records of this type.'}
        </div>
      ) : (
        <div className="timeline-list">
          {grouped.map((entry) => {
            if (entry.type === 'group') {
              const docId = entry.records[0].source_document_id;
              const firstForDoc = !annotatedDocs.has(docId);
              annotatedDocs.add(docId);
              return (
                <GroupedRecordBox
                  key={`group-${entry.groupType}-${docId}`}
                  records={entry.records}
                  groupType={entry.groupType}
                  anchorId={firstForDoc ? `doc-${docId}` : undefined}
                  prescriber={entry.groupType === 'medicines' ? {
                    canEdit: user?.role === 'patient',
                    locked: (linksByDoc.get(docId) || []).some((l) => l.status === 'confirmed'),
                    onSaved: load,
                  } : undefined}
                >
                  {firstForDoc && <PrescriptionLinkPanel links={linksByDoc.get(docId)} />}
                </GroupedRecordBox>
              );
            }
            const link = linkByNote.get(entry.record.id);
            return (
              <TimelineRecord key={entry.record.id} record={entry.record}>
                {link && (
                  <ConsultationLinkPanel
                    link={link}
                    canEdit={canEdit(link)}
                    isPatient={user?.role === 'patient'}
                    onChanged={loadLinks}
                  />
                )}
              </TimelineRecord>
            );
          })}
        </div>
      )}
    </div>
  );
}
