import { courseStatus, formatDay, plural } from '../dates';

/**
 * Treatment course of a medication: "10 days · 31 May 2025 – 9 Jun 2025 ·
 * completed 3 days ago". `course` is computed by the API from the duration
 * written on the prescription (backend app/durations.py).
 */
export default function CourseInfo({ course, compact = false }) {
  if (!course) return null;
  if (course.ongoing) {
    return <span className="med-detail-chip course-chip">{course.duration === 'as needed' ? 'As needed' : 'Ongoing'}</span>;
  }
  const status = courseStatus(course);
  const range = `${formatDay(course.start_date)} – ${formatDay(course.end_date)}`;
  if (compact) {
    return (
      <span className={`med-detail-chip course-chip ${status?.state || ''}`} title={`${range} (${status?.label})`}>
        {plural(course.duration_days, 'day')}
      </span>
    );
  }
  return (
    <span className={`course-info ${status?.state || ''}`}>
      <strong>{plural(course.duration_days, 'day')}</strong> · {range}
      {status && <> · {status.label}</>}
    </span>
  );
}
