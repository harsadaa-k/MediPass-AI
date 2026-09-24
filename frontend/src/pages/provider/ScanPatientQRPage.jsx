import { useEffect, useRef, useState } from 'react';
import jsQR from 'jsqr';
import { api } from '../../api';

const CAMERA_ERRORS = {
  NotAllowedError: 'Camera access is blocked. Allow the camera for this site (lock icon in the address bar), or upload a photo of the code below.',
  NotFoundError: 'No camera was found on this device. Upload a photo of the code or paste it below.',
  NotReadableError: 'The camera is in use by another app. Close it and try again, or upload a photo of the code.',
  SecurityError: 'The camera only works on HTTPS or localhost.',
};

// ~8 decodes a second: plenty for a steady hand, light on CPU/battery.
const SCAN_INTERVAL_MS = 120;

function decodeImageData(imageData) {
  const hit = jsQR(imageData.data, imageData.width, imageData.height, { inversionAttempts: 'attemptBoth' });
  return hit?.data || null;
}

/**
 * Doctor scans a patient's MediPass QR code -> patient added instantly.
 * Three ways in: live camera, a photo of the code, or pasting the code.
 */
export default function ScanPatientQRPage({ onAdded }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(0);
  const handledRef = useRef(false); // one scan -> one redeem
  const [cameraOn, setCameraOn] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [pasted, setPasted] = useState('');

  const stopCamera = () => {
    clearTimeout(timerRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraOn(false);
  };

  useEffect(() => stopCamera, []);

  const redeem = async (code) => {
    if (handledRef.current) return;
    handledRef.current = true;
    stopCamera();
    setError('');
    setStatus('Adding patient…');
    try {
      const result = await api.redeemPatientQR(code);
      onAdded?.(result);
    } catch (err) {
      handledRef.current = false;
      setStatus('');
      setError(err.detail || 'Could not add the patient from this code.');
    }
  };

  const scanFrame = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !streamRef.current) return;
    if (video.readyState >= 2 && video.videoWidth) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(video, 0, 0);
      const code = decodeImageData(ctx.getImageData(0, 0, canvas.width, canvas.height));
      if (code) {
        redeem(code);
        return;
      }
    }
    timerRef.current = setTimeout(scanFrame, SCAN_INTERVAL_MS);
  };

  const startCamera = async () => {
    setError('');
    setStatus('');
    handledRef.current = false;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError(CAMERA_ERRORS.SecurityError);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      });
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      setCameraOn(true);
      setStatus('Point the camera at the patient\'s QR code…');
      timerRef.current = setTimeout(scanFrame, SCAN_INTERVAL_MS);
    } catch (err) {
      setError(CAMERA_ERRORS[err?.name] || `Couldn't start the camera (${err?.name || err}).`);
    }
  };

  const scanFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError('');
    handledRef.current = false;
    try {
      const bitmap = await createImageBitmap(file);
      const canvas = canvasRef.current;
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(bitmap, 0, 0);
      const code = decodeImageData(ctx.getImageData(0, 0, bitmap.width, bitmap.height));
      if (code) redeem(code);
      else setError('No QR code found in that image. Try a sharper, closer photo.');
    } catch {
      setError('That file could not be read as an image.');
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Scan patient QR</h1>
        <p>
          Ask the patient to open <strong>My QR code</strong> in MediPass and scan it. They're added to your
          patients immediately, with the sharing they chose — no access request needed.
        </p>
      </div>

      <div className="surface" style={{ maxWidth: 620, marginBottom: '1.5rem' }}>
        <div className="qr-scanner" style={{ display: cameraOn ? 'block' : 'none' }}>
          <video ref={videoRef} playsInline muted />
          <div className="qr-scanner-frame" />
        </div>
        <canvas ref={canvasRef} style={{ display: 'none' }} />

        {status && <p className="muted" style={{ margin: '0.6rem 0' }}>{status}</p>}
        {error && <p className="error-text">{error}</p>}

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem' }}>
          {!cameraOn ? (
            <button className="btn btn-primary" onClick={startCamera}>📷 Start camera</button>
          ) : (
            <button className="btn btn-secondary" onClick={stopCamera}>Stop camera</button>
          )}
          <label className="btn btn-secondary" style={{ cursor: 'pointer' }}>
            Upload a photo of the code
            <input type="file" accept="image/*" onChange={scanFile} style={{ display: 'none' }} />
          </label>
        </div>
      </div>

      <div className="surface" style={{ maxWidth: 620 }}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handledRef.current = false;
            if (pasted.trim()) redeem(pasted.trim());
          }}
        >
          <div className="field">
            <label htmlFor="qr-paste">Or paste the code / link</label>
            <input
              id="qr-paste"
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              placeholder="e.g. http://localhost:5173/add-patient/… or the code itself"
            />
          </div>
          <button type="submit" className="btn btn-secondary btn-sm" disabled={!pasted.trim()}>
            Add patient
          </button>
        </form>
      </div>
    </div>
  );
}
