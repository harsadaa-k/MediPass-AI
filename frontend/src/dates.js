// Calendar-day helpers. Record dates ("2025-05-31") are calendar days, not
// instants: `new Date('2025-05-31')` would be UTC midnight and shift a day
// in time zones behind UTC. These work on local calendar days only, so day
// counts are the same in every time zone and across DST changes.

const MS_PER_DAY = 24 * 60 * 60 * 1000;

// "2025-05-31" -> local Date at midnight (null if missing/invalid)
export function parseDay(value) {
  if (!value) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? null : d;
}

// Today's local calendar date as "YYYY-MM-DD" (toISOString() would give the UTC day)
export function todayISO(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// Whole calendar days from a to b (b - a); Date or "YYYY-MM-DD"
export function daysBetween(a, b) {
  const da = typeof a === 'string' ? parseDay(a) : a;
  const db = typeof b === 'string' ? parseDay(b) : b;
  if (!da || !db) return null;
  const ua = Date.UTC(da.getFullYear(), da.getMonth(), da.getDate());
  const ub = Date.UTC(db.getFullYear(), db.getMonth(), db.getDate());
  return Math.round((ub - ua) / MS_PER_DAY);
}

export function daysSince(day, now = new Date()) {
  return daysBetween(day, now);
}

export function formatDay(value) {
  const d = typeof value === 'string' ? parseDay(value) : value;
  return d ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '';
}

export function plural(n, word) {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

// "today", "yesterday", "5 days ago", "in 3 days"
export function relativeDays(n) {
  if (n == null) return '';
  if (n === 0) return 'today';
  if (n === -1) return 'yesterday';
  if (n === 1) return 'tomorrow';
  return n < 0 ? `${plural(-n, 'day')} ago` : `in ${plural(n, 'day')}`;
}

// Where a medication course stands today. `course` comes from the API
// (start_date, end_date, duration_days; see backend app/durations.py).
export function courseStatus(course, now = new Date()) {
  if (!course || course.ongoing || !course.end_date) return null;
  const today = todayISO(now);
  const toStart = daysBetween(today, course.start_date);
  const toEnd = daysBetween(today, course.end_date);
  if (toStart > 0) return { state: 'upcoming', label: `starts ${relativeDays(toStart)}` };
  if (toEnd >= 0) {
    const day = daysBetween(course.start_date, today) + 1;
    return { state: 'active', label: `day ${day} of ${course.duration_days} · ${plural(toEnd + 1, 'day')} left` };
  }
  return { state: 'completed', label: `completed ${relativeDays(toEnd)}` };
}
