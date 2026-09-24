// Scroll to a timeline card and flash it (same idea as the AI summary citations).
export function jumpTo(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return false;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.add('link-flash');
  setTimeout(() => el.classList.remove('link-flash'), 1800);
  return true;
}
