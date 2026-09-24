export default function FlagBanner({ flag }) {
  return (
    <div className="flag-banner">
      <span aria-hidden="true">{flag.type === 'conflict' ? '⚠' : '—'}</span>
      <span>{flag.message}</span>
    </div>
  );
}
