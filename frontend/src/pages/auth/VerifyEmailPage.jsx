import { useState, useEffect } from 'react';
import { api } from '../../api';

export default function VerifyEmailPage() {
  const [status, setStatus] = useState('verifying');
  const [error, setError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');

    if (!token) {
      setStatus('error');
      setError('Invalid or missing verification token.');
      return;
    }

    const verify = async () => {
      try {
        await api.verifyEmail(token);
        setStatus('success');
      } catch (err) {
        setStatus('error');
        setError(err.detail || 'Verification failed. The token may be expired.');
      }
    };

    verify();
  }, []);

  return (
    <div style={{ maxWidth: 400, margin: '4rem auto', textAlign: 'center' }}>
      <h2>Email Verification</h2>
      
      {status === 'verifying' && <p>Verifying your email address...</p>}
      
      {status === 'success' && (
        <div style={{ padding: '1rem', background: '#d1fae5', color: '#065f46', borderRadius: '8px' }}>
          <h3>Verification Successful!</h3>
          <p>Your email has been verified. You can now log in.</p>
          <a href="/login" className="btn btn-primary" style={{ display: 'inline-block', marginTop: '1rem' }}>Go to Login</a>
        </div>
      )}
      
      {status === 'error' && (
        <div style={{ padding: '1rem', background: '#fee2e2', color: '#991b1b', borderRadius: '8px' }}>
          <h3>Verification Failed</h3>
          <p>{error}</p>
          <a href="/login" className="btn btn-secondary" style={{ display: 'inline-block', marginTop: '1rem' }}>Back to Login</a>
        </div>
      )}
    </div>
  );
}
