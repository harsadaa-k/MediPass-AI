const VARIANT_BY_STATUS = {
  unverified: 'amber',
  patient_verified: 'teal',
  provider_verified: 'blue',
  conflict: 'amber',
  pending: 'amber',
  approved: 'green',
  denied: 'gray',
  revoked: 'gray',
};

const LABEL_BY_STATUS = {
  unverified: 'Needs review',
  patient_verified: 'Verified by you',
  provider_verified: 'Added by provider',
  conflict: 'Conflict',
  pending: 'Pending',
  approved: 'Approved',
  denied: 'Denied',
  revoked: 'Revoked',
};

export default function Badge({ status, children }) {
  const variant = VARIANT_BY_STATUS[status] || 'gray';
  const label = children || LABEL_BY_STATUS[status] || status;
  return <span className={`badge badge-${variant}`}>{label}</span>;
}
