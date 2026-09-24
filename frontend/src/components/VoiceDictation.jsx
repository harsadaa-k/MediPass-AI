import { useState, useRef, useEffect } from 'react';
import { api } from '../api';
import { todayISO } from '../dates';
import { getSpeechRecognition, SPEECH_ERRORS, runMicChecks, createLevelMeter } from './micDiagnostics';

/**
 * VoiceDictation — a self-contained voice recording component for doctors.
 *
 * Props:
 *   onApply(structured) — called when the doctor clicks "Apply to form" with
 *                          the AI-structured fields (record_type, title, record_date, details)
 *
 * States: idle → checking → recording → stopping → processing → review → idle
 *         (any step can go to error, which lists which microphone check failed)
 *
 * Reliability notes:
 *  - Chrome delivers the last recognised words *after* stop(), so we wait for
 *    onend before reading the transcript (previously a quick Stop gave
 *    "No speech was captured" even though the doctor had spoken).
 *  - Chrome ends a continuous session on its own after a pause; we restart it
 *    while the doctor is still recording and keep the transcript so far.
 *  - A live level meter shows whether audio is actually reaching the browser.
 */

const SILENCE_WARNING_SECONDS = 4;
const STOP_FLUSH_TIMEOUT_MS = 2000;
const recognitionLang = () => {
  const lang = typeof navigator !== 'undefined' ? navigator.language : '';
  return lang && lang.toLowerCase().startsWith('en') ? lang : 'en-US';
};

export default function VoiceDictation({ onApply }) {
  const [state, setState] = useState('idle'); // idle | checking | recording | stopping | processing | review | error
  const [transcript, setTranscript] = useState('');
  const [interimText, setInterimText] = useState('');
  const [structured, setStructured] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [checks, setChecks] = useState([]);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [silent, setSilent] = useState(false);
  const [deviceLabel, setDeviceLabel] = useState('');

  const recognitionRef = useRef(null);
  const timerRef = useRef(null);
  const meterRef = useRef(null);
  const meterTimerRef = useRef(null);
  const streamRef = useRef(null);
  const finalRef = useRef('');        // finalised text across restarts
  const interimRef = useRef('');
  const recordingRef = useRef(false); // true while the doctor wants to record
  const endResolverRef = useRef(null);
  const lastSoundRef = useRef(0);
  const heardSpeechRef = useRef(false);
  const soundDetectedRef = useRef(false); // meter saw real input at some point

  const releaseAudio = () => {
    clearInterval(timerRef.current);
    clearInterval(meterTimerRef.current);
    meterRef.current?.close();
    meterRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setLevel(0);
  };

  // Stop everything if the form unmounts mid-recording
  useEffect(() => () => {
    recordingRef.current = false;
    try { recognitionRef.current?.abort(); } catch { /* not started */ }
    releaseAudio();
  }, []);

  const fail = (message, failedChecks = []) => {
    recordingRef.current = false;
    try { recognitionRef.current?.abort(); } catch { /* not started */ }
    recognitionRef.current = null;
    releaseAudio();
    setErrorMsg(message);
    setChecks(failedChecks);
    setState('error');
  };

  const startRecognition = () => {
    const SpeechRecognition = getSpeechRecognition();
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = recognitionLang();

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalRef.current = `${finalRef.current} ${result[0].transcript}`.trim();
        } else {
          interim += result[0].transcript;
        }
      }
      interimRef.current = interim;
      heardSpeechRef.current = true;
      setTranscript(finalRef.current);
      setInterimText(interim);
    };

    recognition.onerror = (event) => {
      if (event.error === 'no-speech' || event.error === 'aborted') return; // onend restarts / stop handles it
      fail(SPEECH_ERRORS[event.error] || `Voice error: ${event.error}. Please try again or type manually.`);
    };

    recognition.onend = () => {
      // Session ended: either we asked it to (stop) or Chrome ended it after a pause.
      if (endResolverRef.current) {
        endResolverRef.current();
        endResolverRef.current = null;
        return;
      }
      if (recordingRef.current) {
        // keep any unfinished phrase, then resume listening
        if (interimRef.current) {
          finalRef.current = `${finalRef.current} ${interimRef.current}`.trim();
          interimRef.current = '';
          setTranscript(finalRef.current);
          setInterimText('');
        }
        try {
          startRecognition();
        } catch {
          fail('Voice recognition stopped unexpectedly. Please try again or type manually.');
        }
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
  };

  const startRecording = async () => {
    setTranscript('');
    setInterimText('');
    setStructured(null);
    setErrorMsg('');
    setChecks([]);
    setElapsed(0);
    setSilent(false);
    finalRef.current = '';
    interimRef.current = '';
    heardSpeechRef.current = false;
    soundDetectedRef.current = false;
    setState('checking');

    const result = await runMicChecks();
    if (!result.ok) {
      const failed = result.checks.find((c) => !c.ok);
      fail(failed?.detail || 'The microphone could not be started.', result.checks);
      return;
    }
    const mutedCheck = result.checks.find((c) => !c.ok);
    streamRef.current = result.stream;
    setDeviceLabel(result.deviceLabel);

    // Live level meter + "can't hear you" detection
    meterRef.current = createLevelMeter(result.stream);
    lastSoundRef.current = Date.now();
    meterTimerRef.current = setInterval(() => {
      const v = meterRef.current?.read();
      if (v == null) return;
      setLevel(v);
      if (v > 0.04) {
        lastSoundRef.current = Date.now();
        soundDetectedRef.current = true;
      }
      setSilent(Date.now() - lastSoundRef.current > SILENCE_WARNING_SECONDS * 1000);
    }, 120);

    try {
      recordingRef.current = true;
      startRecognition();
    } catch (err) {
      fail(`Voice recognition couldn't start (${err?.message || err}). Please try again or type manually.`, result.checks);
      return;
    }
    if (mutedCheck) setSilent(true);
    setState('recording');
    timerRef.current = setInterval(() => setElapsed((prev) => prev + 1), 1000);
  };

  const stopRecording = async () => {
    recordingRef.current = false;
    setState('stopping');
    const recognition = recognitionRef.current;
    if (recognition) {
      // Wait for the last results to arrive (they come after stop()).
      await new Promise((resolve) => {
        endResolverRef.current = resolve;
        try { recognition.stop(); } catch { resolve(); }
        setTimeout(resolve, STOP_FLUSH_TIMEOUT_MS);
      });
      endResolverRef.current = null;
      recognitionRef.current = null;
    }
    releaseAudio();

    const finalTranscript = `${finalRef.current} ${interimRef.current}`.trim();
    if (!finalTranscript) {
      setErrorMsg(
        heardSpeechRef.current || soundDetectedRef.current
          ? 'Your microphone picked up sound, but no words were recognised. Speak a little closer to the mic and try again, or type manually.'
          : `No sound reached the browser from "${deviceLabel || 'your microphone'}". Check it isn't muted and that it's the input device selected in Windows Sound settings (or Chrome's site settings), then try again.`
      );
      setChecks([]);
      setState('error');
      return;
    }

    setState('processing');
    try {
      const result = await api.structureVoiceTranscript(finalTranscript);
      setStructured(result);
      setState('review');
    } catch (err) {
      setErrorMsg(err.detail || 'Failed to process the voice input. Your transcript is preserved below.');
      setStructured({
        record_type: 'consultation',
        title: 'Voice dictation',
        record_date: todayISO(),
        details: { notes: finalTranscript },
        warnings: ['AI processing failed. Raw transcript placed in notes.'],
      });
      setState('review');
    }
  };

  const cancelRecording = () => {
    recordingRef.current = false;
    try { recognitionRef.current?.abort(); } catch { /* not started */ }
    recognitionRef.current = null;
    releaseAudio();
    setState('idle');
    setTranscript('');
    setInterimText('');
    setElapsed(0);
  };

  const handleApply = () => {
    if (structured && onApply) {
      onApply(structured);
    }
    setState('idle');
    setStructured(null);
    setTranscript('');
    setInterimText('');
  };

  const handleDiscard = () => {
    setState('idle');
    setStructured(null);
    setTranscript('');
    setInterimText('');
    setErrorMsg('');
    setChecks([]);
  };

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  return (
    <div className="voice-dictation">
      {/* ---- IDLE: Just the mic button ---- */}
      {state === 'idle' && (
        <button
          type="button"
          className="voice-mic-btn"
          onClick={startRecording}
          title={getSpeechRecognition() ? 'Dictate with voice' : 'Voice dictation is not supported in this browser'}
          aria-label="Start voice dictation"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
            <line x1="12" y1="19" x2="12" y2="23"/>
            <line x1="8" y1="23" x2="16" y2="23"/>
          </svg>
        </button>
      )}

      {/* ---- CHECKING / STOPPING: short spinners ---- */}
      {(state === 'checking' || state === 'stopping') && (
        <div className="voice-recording-panel">
          <div className="voice-processing">
            <span className="voice-spinner" />
            <span>{state === 'checking' ? 'Checking your microphone…' : 'Finishing up…'}</span>
          </div>
        </div>
      )}

      {/* ---- RECORDING: Pulsing indicator + timer + level + transcript + controls ---- */}
      {state === 'recording' && (
        <div className="voice-recording-panel">
          <div className="voice-recording-header">
            <span className="voice-pulse-dot" />
            <span className="voice-recording-label">Recording…</span>
            <span className="voice-timer mono">{formatTime(elapsed)}</span>
          </div>
          <div className="voice-level" title="Microphone input level">
            <div className="voice-level-bar" style={{ width: `${Math.round(level * 100)}%` }} />
          </div>
          <div className="muted" style={{ fontSize: '0.78rem', marginBottom: '0.4rem' }}>
            Listening via {deviceLabel || 'your default microphone'}
          </div>
          {silent && (
            <p className="voice-warning-text" style={{ margin: '0 0 0.4rem 0' }}>
              ⚠️ We can't hear anything from this microphone. Check it isn't muted, or choose the right input
              device in Windows Sound settings / Chrome site settings.
            </p>
          )}
          <div className="voice-transcript-live">
            {transcript && <span>{transcript} </span>}
            {interimText && <span className="voice-interim">{interimText}</span>}
            {!transcript && !interimText && (
              <span className="muted">Start speaking…</span>
            )}
          </div>
          <div className="voice-recording-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={stopRecording}>
              ⏹ Stop & Process
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={cancelRecording}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ---- PROCESSING: Spinner ---- */}
      {state === 'processing' && (
        <div className="voice-recording-panel">
          <div className="voice-processing">
            <span className="voice-spinner" />
            <span>Structuring your dictation with AI…</span>
          </div>
        </div>
      )}

      {/* ---- REVIEW: Show structured result ---- */}
      {state === 'review' && structured && (
        <div className="voice-review-panel">
          <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '0.95rem' }}>
            🎙️ Voice Dictation Result
          </h4>
          {structured.warnings && structured.warnings.length > 0 && (
            <div className="voice-warnings">
              {structured.warnings.map((w, i) => (
                <p key={i} className="voice-warning-text">⚠️ {w}</p>
              ))}
            </div>
          )}
          <div className="voice-review-fields">
            <div className="voice-review-row">
              <span className="voice-review-label">Type:</span>
              <span className="badge badge-teal">{structured.record_type?.replace('_', ' ')}</span>
            </div>
            <div className="voice-review-row">
              <span className="voice-review-label">Title:</span>
              <span>{structured.title}</span>
            </div>
            <div className="voice-review-row">
              <span className="voice-review-label">Date:</span>
              <span className="mono">{structured.record_date}</span>
            </div>
            {structured.details?.medicine && (
              <div className="voice-review-row">
                <span className="voice-review-label">Medicine:</span>
                <span>{structured.details.medicine}</span>
              </div>
            )}
            {structured.details?.dose && (
              <div className="voice-review-row">
                <span className="voice-review-label">Dose:</span>
                <span>{structured.details.dose}</span>
              </div>
            )}
            {structured.details?.notes && (
              <div className="voice-review-row">
                <span className="voice-review-label">Notes:</span>
                <span>{structured.details.notes}</span>
              </div>
            )}
            {structured.details?.text && (
              <div className="voice-review-row">
                <span className="voice-review-label">Details:</span>
                <span>{structured.details.text}</span>
              </div>
            )}
            {structured.details?.follow_up && (
              <div className="voice-review-row">
                <span className="voice-review-label">Follow-up:</span>
                <span>{structured.details.follow_up}</span>
              </div>
            )}
          </div>
          <div className="voice-review-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={handleApply}>
              ✓ Apply to form
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={handleDiscard}>
              Discard
            </button>
          </div>
        </div>
      )}

      {/* ---- ERROR: Message with retry ---- */}
      {state === 'error' && (
        <div className="voice-recording-panel">
          <p className="error-text" style={{ margin: '0 0 0.5rem 0', fontSize: '0.88rem' }}>{errorMsg}</p>
          {checks.length > 0 && (
            <ul className="voice-checks">
              {checks.map((c) => (
                <li key={c.label} className={c.ok ? 'ok' : 'fail'}>
                  {c.ok ? '✓' : '✗'} {c.label}
                  {c.ok && c.detail ? <span className="muted"> — {c.detail}</span> : null}
                </li>
              ))}
            </ul>
          )}
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {getSpeechRecognition() && (
              <button type="button" className="btn btn-primary btn-sm" onClick={startRecording}>
                Try again
              </button>
            )}
            <button type="button" className="btn btn-secondary btn-sm" onClick={handleDiscard}>
              Back to manual entry
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
