// Microphone pre-flight checks for voice dictation.
//
// Browsers don't expose drivers or hardware details, so "driver/hardware"
// problems are detected indirectly: no input device listed, getUserMedia
// failing with NotReadableError (device busy / driver fault), or a live
// stream that carries no signal.

// Looked up at call time (not module load) so late-loaded polyfills work.
export const getSpeechRecognition = () =>
  (typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)) || null;

const GUM_ERRORS = {
  NotAllowedError:
    'Microphone access is blocked. Click the lock icon in the address bar → Site settings → Microphone → Allow, then reload. ' +
    'On Windows also check Settings → Privacy & security → Microphone → "Let apps access your microphone" and "Let desktop apps access your microphone".',
  SecurityError: 'The browser blocked microphone access for this page (it must be served over HTTPS or localhost).',
  NotFoundError: 'No microphone was found. Plug one in (or enable the built-in mic) and try again.',
  NotReadableError:
    'The microphone is present but can\'t be opened — another app (Zoom, Teams, Discord…) may be using it, ' +
    'or its driver has a problem. Close other apps using the mic, or re-plug / update the audio driver.',
  OverconstrainedError: 'The selected microphone doesn\'t support the requested settings.',
  AbortError: 'The microphone stopped unexpectedly while starting. Try again, or re-plug the device.',
};

export const SPEECH_ERRORS = {
  'not-allowed': GUM_ERRORS.NotAllowedError,
  'service-not-allowed':
    'This browser\'s speech service is disabled or blocked (common in Brave and some managed browsers). Use Chrome or Edge.',
  'audio-capture': 'The speech service couldn\'t capture audio from your microphone. ' + GUM_ERRORS.NotReadableError,
  network:
    'The browser\'s speech-recognition service couldn\'t be reached (Chrome and Edge send audio to their cloud service). ' +
    'Check your internet connection / firewall and try again.',
  'language-not-supported': 'Speech recognition doesn\'t support the selected language in this browser.',
  'bad-grammar': 'Speech recognition failed to start. Try again.',
};

/**
 * Runs the checks in order and stops at the first blocking failure.
 * Returns { ok, checks: [{label, ok, detail}], stream, deviceLabel }.
 * On success the caller owns `stream` and must stop its tracks.
 */
export async function runMicChecks() {
  const checks = [];
  const add = (label, ok, detail = '') => checks.push({ label, ok, detail });
  const fail = () => ({ ok: false, checks, stream: null, deviceLabel: '' });

  // 1. Browser support
  if (!getSpeechRecognition()) {
    add('Browser supports speech recognition', false,
      'Voice dictation needs Chrome or Edge on desktop/Android, or Safari 14.1+. Firefox doesn\'t support it — please type instead.');
    return fail();
  }
  add('Browser supports speech recognition', true);

  // 2. Secure context (mic is blocked on plain http:// except localhost)
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    add('Page allowed to use the microphone', false,
      `Microphones only work on HTTPS or localhost. You're on ${window.location.origin} — open the app via localhost or HTTPS.`);
    return fail();
  }
  add('Page allowed to use the microphone', true);

  // 3. Permission state (not all browsers support querying it)
  try {
    const perm = await navigator.permissions?.query({ name: 'microphone' });
    if (perm?.state === 'denied') {
      add('Microphone permission', false, GUM_ERRORS.NotAllowedError);
      return fail();
    }
    add('Microphone permission', true, perm?.state === 'prompt' ? 'The browser will ask you to allow it.' : '');
  } catch {
    add('Microphone permission', true, 'Will be requested when recording starts.');
  }

  // 4. Hardware present (labels are hidden until permission is granted, but count is visible)
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    if (!devices.some((d) => d.kind === 'audioinput')) {
      add('Microphone detected', false, GUM_ERRORS.NotFoundError);
      return fail();
    }
    add('Microphone detected', true);
  } catch {
    add('Microphone detected', true, 'Could not list devices; continuing.');
  }

  // 5. Open the default input (the same device speech recognition uses)
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    add('Microphone opens', false, GUM_ERRORS[err?.name] || `Couldn't open the microphone (${err?.name || err}).`);
    return fail();
  }
  const track = stream.getAudioTracks()[0];
  if (!track || track.readyState !== 'live') {
    stream.getTracks().forEach((t) => t.stop());
    add('Microphone opens', false, GUM_ERRORS.NotReadableError);
    return fail();
  }
  add('Microphone opens', true, track.label ? `Using: ${track.label}` : '');
  if (track.muted) {
    add('Microphone unmuted', false,
      'The system reports this microphone as muted. Unmute it (hardware switch, keyboard key, or Windows Sound settings).');
  }

  return { ok: true, checks, stream, deviceLabel: track.label || 'default microphone' };
}

/**
 * Live input level (0..1) from a stream, for the recording meter and the
 * "we can't hear you" warning. Returns { read(), close() }.
 */
export function createLevelMeter(stream) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return { read: () => null, close: () => {} };
  const ctx = new Ctx();
  // Contexts can start suspended (autoplay policy); the meter would read 0.
  ctx.resume().catch(() => {});
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  return {
    read() {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      return Math.min(1, rms * 8); // speech at normal volume ≈ 0.2–0.8
    },
    close() {
      try { source.disconnect(); } catch { /* already closed */ }
      ctx.close().catch(() => {});
    },
  };
}
