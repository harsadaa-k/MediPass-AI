import { SORTS } from '../recordSort';

export default function RecordSortSelect({ value, onChange, exclude = [] }) {
  return (
    <label>
      Sort by
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.entries(SORTS).filter(([k]) => !exclude.includes(k)).map(([k, label]) => (
          <option key={k} value={k}>{label}</option>
        ))}
      </select>
    </label>
  );
}
