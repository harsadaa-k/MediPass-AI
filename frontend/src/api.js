const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

const TOKEN_KEY = 'medipass_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : 'Request failed');
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = 'GET', body, form, formData, auth = true, headers: customHeaders = {} } = {}) {
  const headers = { ...customHeaders };
  if (body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  // formData (multipart) must NOT set Content-Type manually -- the browser
  // needs to add its own boundary parameter, which we'd break by setting it.
  if (auth) {
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: formData ? formData : form ? form : body ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined,
  });

  let payload = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail = payload && payload.detail ? payload.detail : `Error ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return payload;
}

export const api = {
  // ---- auth ----
  register: (payload) => request('/auth/register', { method: 'POST', body: payload, auth: false }),
  login: (email, password) => {
    const formData = new URLSearchParams();
    formData.append('username', email);
    formData.append('password', password);
    return request('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData.toString(),
      auth: false,
    });
  },
  me: () => request('/auth/me'),
  getMe: () => request('/auth/me'),
  verifyEmail: (token) => request('/auth/verify-email', { method: 'POST', body: { token }, auth: false }),
  resendVerification: (email) => request('/auth/resend-verification', { method: 'POST', body: { email }, auth: false }),
  forgotPassword: (email) => request('/auth/forgot-password', { method: 'POST', body: { email }, auth: false }),
  resetPassword: (token, newPassword) => request('/auth/reset-password', { method: 'POST', body: { token, new_password: newPassword }, auth: false }),

  // ---- documents ----
  uploadDocument: (file, documentType, allowDuplicate = false) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType || 'prescription');
    if (allowDuplicate) formData.append('allow_duplicate', 'true');
    return request('/documents/upload', { method: 'POST', formData });
  },
  getDocument: (id) => request(`/documents/${id}`),
  setPrescriber: (id, doctorName, hospitalName) =>
    request(`/documents/${id}/prescriber`, { method: 'PATCH', body: { doctor_name: doctorName, hospital_name: hospitalName } }),
  getDocumentFileBlob: async (id) => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/documents/${id}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const payload = await res.json();
        if (payload && payload.detail) detail = payload.detail;
      } catch {
        /* ignore parse failure, keep generic detail */
      }
      throw new ApiError(res.status, detail);
    }
    return res.blob();
  },

  // ---- records ----
  listUnverified: () => request('/records/unverified'),
  listBodyParts: () => request('/records/body-parts'),
  verifyRecord: (id, data) => request(`/records/${id}/verify`, { method: 'POST', body: data || {} }),
  deleteRecord: (id) => request(`/records/${id}`, { method: 'DELETE' }),

  // ---- timeline ----
  getTimeline: (patientId) => request(`/timeline/${patientId}`),
  getTimelineSummary: (patientId) => request(`/timeline/${patientId}/summary`),

  // ---- access ----
  requestAccess: (patientId) => request('/access-requests', { method: 'POST', body: { patient_id: patientId } }),
  listPendingRequests: () => request('/access-requests/pending'),
  listMyGrantsAsPatient: () => request('/access-requests/for-me'),
  listMyGrantsAsProvider: () => request('/access-requests/mine'),
  respondToRequest: (grantId, approve, scope, expiryDays = 30) =>
    request(`/access-requests/${grantId}/respond`, { method: 'POST', body: { approve, scope, expiry_days: expiryDays } }),
  revokeAccess: (grantId) => request(`/access-requests/${grantId}/revoke`, { method: 'POST' }),
  lookupPatient: (email) => request(`/users/lookup-patient?email=${encodeURIComponent(email)}`),
  getAiSharingRecommendation: (grantId) => request(`/access-requests/${grantId}/recommendation`),
  getBadges: () => request('/users/badges'),

  // ---- patient QR codes (patient shows, doctor scans) ----
  createPatientQR: (scope, accessDays, validMinutes) =>
    request('/patient-qr', { method: 'POST', body: { scope, access_days: accessDays, valid_minutes: validMinutes } }),
  getPatientQR: (id) => request(`/patient-qr/${id}`),
  revokePatientQR: (id) => request(`/patient-qr/${id}/revoke`, { method: 'POST' }),
  redeemPatientQR: (code) => request('/patient-qr/redeem', { method: 'POST', body: { code } }),

  // ---- consultation note <-> prescription links ----
  getRecordLinks: (patientId) => request(`/links/patient/${patientId}`),
  getLinkCandidates: (consultationId) => request(`/links/consultation/${consultationId}/candidates`),
  overrideLink: (consultationId, documentId, reason) =>
    request(`/links/consultation/${consultationId}/override`, {
      method: 'POST', body: { document_id: documentId, reason },
    }),
  acceptLink: (linkId) => request(`/links/${linkId}/accept`, { method: 'POST' }),
  rejectLink: (linkId, reason) => request(`/links/${linkId}/reject`, { method: 'POST', body: { reason } }),

  // ---- doctor verification ----
  getMyVerification: () => request('/doctor-verification/me'),
  submitVerification: (fields, certificateFile) => {
    const formData = new FormData();
    Object.entries(fields).forEach(([k, v]) => { if (v !== '' && v != null) formData.append(k, v); });
    if (certificateFile) formData.append('certificate', certificateFile);
    return request('/doctor-verification', { method: 'POST', formData });
  },

  getVerificationDocument: () => request('/doctor-verification/document'),

  // ---- provider: active patients ----
  getProviderPatients: () => request('/provider/patients'),
  setPatientStatus: (patientId, status, note) =>
    request(`/provider/patients/${patientId}/status`, { method: 'PUT', body: { status, note } }),

  // ---- consultations ----
  addConsultation: (data) => request('/consultations', { method: 'POST', body: data }),
  listMyRecentConsultations: (limit = 5) => request(`/consultations/mine?limit=${limit}`),
  structureVoiceTranscript: (transcript) => request('/consultations/voice-structure', { method: 'POST', body: { transcript } }),


  // ---- audit ----
  getAuditLog: () => request('/audit-log'),

  // ---- notifications ----
  getNotifications: () => request('/notifications'),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: 'POST' }),
  
  // ---- profiles ----
  updateProviderProfile: (data) => request('/auth/profile/provider', { method: 'PUT', body: data }),
};

export { ApiError };
