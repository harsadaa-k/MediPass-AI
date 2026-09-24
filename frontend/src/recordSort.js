import { parseUtc } from './grants';

// Sorting for record lists (timeline, medications, lab results).
// "Logged" sorts compare real timestamps: logged_at is naive UTC from the
// API and may or may not carry microseconds, so string comparison isn't
// reliable. Each record's keys are computed once, then sorted (O(n log n)).

export const SORTS = {
  date_desc: 'Consultation date (newest first)',
  date_asc: 'Consultation date (oldest first)',
  logged_desc: 'Logged in MediPass (newest first)',
  logged_asc: 'Logged in MediPass (oldest first)',
  type: 'Record type',
};

export const TYPE_LABELS = {
  medication: 'Medications',
  diagnosis: 'Diagnoses',
  lab_result: 'Lab results & imaging',
  consultation: 'Consultations',
  allergy: 'Allergies',
  hospitalization: 'Hospitalizations',
};

const STORAGE_KEY = 'medipass_record_sort';

export function readSavedSort(fallback = 'date_asc') {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved && SORTS[saved] ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function saveSort(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // storage blocked: the choice just isn't remembered
  }
}

export function sortRecords(records, sort) {
  const keyed = records.map((r) => ({
    r,
    date: r.record_date || '',
    logged: parseUtc(r.logged_at)?.getTime() ?? 0,
    type: TYPE_LABELS[r.record_type] || r.record_type,
  }));
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  // ties: consultation date, then logged time, then title -- a stable order
  const byDate = (a, b) => cmp(a.date, b.date) || a.logged - b.logged || cmp(a.r.title, b.r.title);
  const byLogged = (a, b) => a.logged - b.logged || byDate(a, b);
  const compare = {
    date_asc: byDate,
    date_desc: (a, b) => byDate(b, a),
    logged_asc: byLogged,
    logged_desc: (a, b) => byLogged(b, a),
    type: (a, b) => cmp(a.type, b.type) || byDate(b, a),
  }[sort] || byDate;
  return keyed.sort(compare).map((k) => k.r);
}
