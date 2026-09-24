import { useState } from 'react';
import { api } from '../api';

export default function ViewSourceButton({ documentId }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const openSource = async () => {
    setLoading(true);
    setError('');
    try {
      const blob = await api.getDocumentFileBlob(documentId);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      // Revoke well after the new tab has had time to load it.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(err.detail || 'Could not open the source document.');
    } finally {
      setLoading(false);
    }
  };

  if (!documentId) return null;

  return (
    <span>
      <button type="button" className="btn btn-secondary btn-sm" onClick={openSource} disabled={loading}>
        {loading ? 'Opening…' : 'View source'}
      </button>
      {error && <span className="error-text" style={{ marginLeft: '0.5em' }}>{error}</span>}
    </span>
  );
}
