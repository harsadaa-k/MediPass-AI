import { useState } from 'react';
import { useAuth } from '../AuthContext';
import { api } from '../api';

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [role, setRole] = useState('patient');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [emailSent, setEmailSent] = useState(true); // did the verification email go out?
  const [unverified, setUnverified] = useState(false); // login refused: email not verified

  const handleResend = async () => {
    setError('');
    setMessage('');
    setSubmitting(true);
    try {
      await api.resendVerification(email);
      setEmailSent(true);
      setMessage('A new verification link is on its way. Check your inbox and the Spam / Promotions folders.');
    } catch (err) {
      setError(typeof err.detail === 'string' ? err.detail : 'Could not resend the email.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleForgotPassword = async () => {
    if (!email) {
      setError('Please enter your email address first.');
      setMessage('');
      return;
    }
    setError('');
    setMessage('');
    setSubmitting(true);
    try {
      await api.forgotPassword(email);
      setMessage('If that email exists, a password reset link has been sent.');
    } catch (err) {
      setError(err.detail || 'Failed to send reset link.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');
    setUnverified(false);
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(email, password);
      } else {
        const created = await register({ email, password, full_name: fullName, role });
        setEmailSent(created?.verification_email_sent !== false);
        setMode('verify_sent');
      }
    } catch (err) {
      if (err.detail?.code === 'unverified_exists') {
        // registered before but never verified: the link was sent again
        setEmailSent(err.detail.email_sent !== false);
        setMode('verify_sent');
        setMessage(err.detail.message);
        return;
      }
      if (err.status === 403 && /not verified/i.test(err.detail || '')) setUnverified(true);
      setError(typeof err.detail === 'string' ? err.detail : 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="name">MediPass</div>
          <div className="tagline">One source-traceable medical timeline, shared on your terms.</div>
        </div>

        <div className="surface">
          {mode === 'verify_sent' ? (
            <div style={{ textAlign: 'center' }}>
              {emailSent ? (
                <>
                  <h2>Check your email!</h2>
                  <p style={{ margin: '1rem 0' }}>We've sent a verification link to <strong>{email}</strong>.</p>
                  <p className="muted" style={{ fontSize: '0.9rem' }}>
                    Please click the link in the email to activate your account before logging in. It can take a
                    minute to arrive; if you don't see it, check the <strong>Spam</strong> and <strong>Promotions</strong> folders.
                  </p>
                </>
              ) : (
                <>
                  <h2>Your account is created</h2>
                  <p className="error-text" style={{ margin: '1rem 0' }}>
                    …but we couldn't send the verification email to <strong>{email}</strong>. Try sending it again.
                  </p>
                </>
              )}
              {message && <p style={{ color: 'var(--softgreen)', fontSize: '0.88rem' }}>{message}</p>}
              {error && <p className="error-text">{error}</p>}
              <div style={{ display: 'flex', gap: '0.6rem', justifyContent: 'center', flexWrap: 'wrap', marginTop: '1.2rem' }}>
                <button className="btn btn-secondary" onClick={handleResend} disabled={submitting}>
                  {submitting ? 'Sending…' : 'Resend email'}
                </button>
                <button className="btn btn-primary" onClick={() => { setMode('login'); setError(''); setMessage(''); }}>
                  Return to Login
                </button>
              </div>
            </div>
          ) : (
            <>
              <h2>{mode === 'login' ? 'Log in' : 'Create an account'}</h2>

              <form onSubmit={handleSubmit}>
                {mode === 'register' && (
                  <>
                    <div className="field">
                      <label htmlFor="fullName">Full name</label>
                      <input
                        id="fullName"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        required
                      />
                    </div>

                    <div className="field">
                      <label>I am a</label>
                      <div className="role-picker">
                        <button
                          type="button"
                          className={`role-option ${role === 'patient' ? 'selected' : ''}`}
                          onClick={() => setRole('patient')}
                        >
                          Patient
                        </button>
                        <button
                          type="button"
                          className={`role-option ${role === 'provider' ? 'selected' : ''}`}
                          onClick={() => setRole('provider')}
                        >
                          Doctor
                        </button>
                      </div>
                    </div>
                  </>
                )}

                <div className="field">
                  <label htmlFor="email">Email</label>
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="password">Password</label>
                  <input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    minLength={6}
                    required
                  />
                  {mode === 'login' && (
                    <div style={{ textAlign: 'right', marginTop: '0.4rem' }}>
                      <button
                        type="button"
                        onClick={handleForgotPassword}
                        style={{ fontSize: '0.85rem', color: 'var(--brand)', background: 'none', border: 'none', padding: 0, cursor: 'pointer', textDecoration: 'none' }}
                      >
                        Forgot password?
                      </button>
                    </div>
                  )}
                </div>

                {error && <p className="error-text">{error}</p>}
                {unverified && mode === 'login' && (
                  <button type="button" className="link-edit-btn" onClick={handleResend} disabled={submitting}>
                    Resend verification email
                  </button>
                )}
                {message && <p style={{ color: 'var(--softgreen)', fontSize: '0.9rem', marginTop: '0.5rem', fontWeight: 500 }}>{message}</p>}

                <button type="submit" className="btn btn-primary" disabled={submitting} style={{ width: '100%', justifyContent: 'center', marginTop: '1rem' }}>
                  {submitting ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}
                </button>
              </form>

              <div className="auth-toggle">
                {mode === 'login' ? (
                  <span className="muted">
                    New here?{' '}
                    <button type="button" onClick={() => { setMode('register'); setError(''); }}>
                      Create an account
                    </button>
                  </span>
                ) : (
                  <span className="muted">
                    Already have an account?{' '}
                    <button type="button" onClick={() => { setMode('login'); setError(''); }}>
                      Log in
                    </button>
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
