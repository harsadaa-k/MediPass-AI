// The backend stores naive UTC datetimes and serializes them without a
// timezone suffix, so treat bare ISO strings as UTC when comparing.
export function parseUtc(value) {
  if (!value) return null;
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

// An approved grant only counts as active until it expires. The backend
// flips expired grants to "revoked" lazily (on next access), so the list
// endpoints can still report them as "approved".
export function isActiveGrant(grant, now = new Date()) {
  if (grant.status !== 'approved') return false;
  const expires = parseUtc(grant.expires_at);
  return !expires || expires > now;
}
