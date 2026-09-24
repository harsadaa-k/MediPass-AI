import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';

export default function AiSummaryPanel({ patientId, refreshKey }) {
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!patientId) return;
    
    let isMounted = true;
    const fetchSummary = async () => {
      setLoading(true);
      setError('');
      try {
        const data = await api.getTimelineSummary(patientId);
        if (isMounted) setSummary(data.summary);
      } catch (err) {
        if (isMounted) setError(err.detail || 'Could not generate summary.');
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    
    fetchSummary();
    return () => { isMounted = false; };
  }, [patientId, refreshKey]);

  // Smooth scroll handler for anchor links
  const handleLinkClick = (e) => {
    // Traverse up to find the closest anchor tag in case we clicked an inner element
    const a = e.target.closest('a');
    if (a) {
      const href = a.getAttribute('href');
      if (href && href.startsWith('#')) {
        e.preventDefault();
        const id = href.substring(1);
        const element = document.getElementById(id);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth', block: 'center' });
          // Optional: highlight the element briefly
          element.style.transition = 'background-color 0.5s ease';
          const oldBg = element.style.backgroundColor;
          element.style.backgroundColor = '#fef08a'; // yellow-200
          setTimeout(() => {
            element.style.backgroundColor = oldBg || '';
          }, 1500);
        } else {
          console.warn('Could not find element with id:', id);
        }
      }
    }
  };

  return (
    <div className="section" style={{ marginBottom: '1.5rem', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0', padding: '1.2rem', borderRadius: 'var(--radius)' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.8rem' }}>
        <span style={{ fontSize: '1.2rem', marginRight: '0.5rem' }}>✨</span>
        <h3 style={{ margin: 0, color: '#334155' }}>AI Clinical Summary</h3>
      </div>
      
      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#64748b' }}>
          <div className="spinner" style={{ width: '16px', height: '16px', border: '2px solid #cbd5e1', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite' }}></div>
          <span>Analyzing patient history...</span>
          <style>{`
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
          `}</style>
        </div>
      ) : error ? (
        <p className="error-text">{error}</p>
      ) : (
        <div 
          onClick={handleLinkClick}
          style={{ lineHeight: '1.6', color: '#1e293b', fontSize: '0.95rem' }}
        >
          <ReactMarkdown
            components={{
              a: ({node, ...props}) => <a {...props} style={{ color: '#2563eb', textDecoration: 'none', fontWeight: '500', cursor: 'pointer', padding: '0 2px' }} />
            }}
          >
            {summary}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
