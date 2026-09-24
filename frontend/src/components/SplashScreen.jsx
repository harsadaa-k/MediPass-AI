import { useEffect, useRef } from 'react';

export const SPLASH_MS = 5000;

const FEATURES = [
  { icon: '📄', text: 'Upload prescriptions & reports — AI reads them for you' },
  { icon: '🩺', text: 'Share with verified doctors by QR code' },
  { icon: '🔒', text: 'You decide who sees what, and for how long' },
];

/**
 * Intro screen shown for SPLASH_MS when the app is opened at its main link,
 * before the login page (or the dashboard, if already signed in).
 */
export default function SplashScreen({ onDone }) {
  // Latest callback, so a re-render (e.g. sign-in check finishing) doesn't restart the 5 s.
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    const t = setTimeout(() => done.current(), SPLASH_MS);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="splash" role="dialog" aria-label="Welcome to MediPass">
      <div className="splash-glow" aria-hidden="true" />
      <div className="splash-content">
        <div className="splash-logo" aria-hidden="true">
          <svg viewBox="0 0 64 64" width="84" height="84">
            <path className="splash-shield"
                  d="M32 4 L54 12 V30 C54 44 44 54 32 60 C20 54 10 44 10 30 V12 Z" />
            <polyline className="splash-pulse" points="14,33 23,33 27,24 32,43 37,19 41,33 50,33" />
          </svg>
        </div>
        <h1 className="splash-title">MediPass</h1>
        <p className="splash-tagline">Your medical history, in one trusted timeline.</p>

        <ul className="splash-features">
          {FEATURES.map((f, i) => (
            <li key={f.text} style={{ animationDelay: `${1.2 + i * 0.45}s` }}>
              <span className="splash-feature-icon" aria-hidden="true">{f.icon}</span>
              <span>{f.text}</span>
            </li>
          ))}
        </ul>

        <div className="splash-progress" aria-hidden="true">
          <span style={{ animationDuration: `${SPLASH_MS}ms` }} />
        </div>
        <button type="button" className="splash-skip" onClick={onDone}>
          Skip →
        </button>
      </div>
    </div>
  );
}
