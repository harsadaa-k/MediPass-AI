import { useState, useEffect } from 'react';
import { api } from '../../api';

export default function ResetPasswordPage() {
  const [token, setToken] = useState(null);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get('token'));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    
    setLoading(true);
    setError('');
    setMessage('');
    
    try {
      await api.resetPassword(token, password);
      setMessage('Your password has been successfully reset.');
    } catch (err) {
      setError(err.detail || 'Failed to reset password. The link might be expired.');
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div style={{ maxWidth: 400, margin: '4rem auto', textAlign: 'center', color: '#991b1b' }}>
        <h2>Invalid Link</h2>
        <p>No reset token found in the URL.</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 400, margin: '4rem auto' }}>
      <h2>Set New Password</h2>
      <p>Please enter your new password below.</p>
      
      {message ? (
        <div style={{ marginTop: '1rem', padding: '1rem', background: '#d1fae5', color: '#065f46', borderRadius: '8px', textAlign: 'center' }}>
          <p><strong>{message}</strong></p>
          <a href="/login" className="btn btn-primary" style={{ display: 'inline-block', marginTop: '1rem' }}>Go to Login</a>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="surface" style={{ marginTop: '1rem' }}>
          <div className="field">
            <label>New Password</label>
            <input 
              type="password" 
              required 
              value={password} 
              onChange={e => setPassword(e.target.value)} 
              minLength={6}
            />
          </div>
          <div className="field">
            <label>Confirm New Password</label>
            <input 
              type="password" 
              required 
              value={confirmPassword} 
              onChange={e => setConfirmPassword(e.target.value)} 
              minLength={6}
            />
          </div>
          
          {error && <p className="error-text">{error}</p>}
          
          <button type="submit" className="btn btn-primary" disabled={loading} style={{ width: '100%', marginTop: '1rem' }}>
            {loading ? 'Resetting...' : 'Reset Password'}
          </button>
        </form>
      )}
    </div>
  );
}
