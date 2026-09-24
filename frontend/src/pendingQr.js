// A scanned /add-patient/<token> link waiting for the provider dashboard to
// redeem it (the doctor may need to log in first).
const KEY = 'medipass_pending_patient_qr';

export function savePendingQr(token) {
  try { sessionStorage.setItem(KEY, token); } catch { /* storage blocked */ }
}

export function takePendingQr() {
  try {
    const token = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return token;
  } catch {
    return null;
  }
}
