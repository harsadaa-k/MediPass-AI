import { useEffect, useState } from 'react';
import { api } from '../../api';
import { parseUtc } from '../../grants';
import VerificationDocument from './VerificationDocument';

const COUNCILS = [
  'National Medical Commission (NMC)',
  'Andhra Pradesh Medical Council',
  'Delhi Medical Council',
  'Gujarat Medical Council',
  'Karnataka Medical Council',
  'Kerala State Medical Councils',
  'Maharashtra Medical Council',
  'Tamil Nadu Medical Council',
  'Telangana State Medical Council',
  'Uttar Pradesh Medical Council',
  'West Bengal Medical Council',
];

const EMPTY_EDU = { degree: '', institution: '', year: '' };
const THIS_YEAR = new Date().getFullYear();

const STATUS_TEXT = {
  not_submitted: 'Not submitted',
  pending: 'Under review',
  verified: '✓ Verified doctor',
  rejected: 'Not approved',
};

/**
 * Doctor profile + verification: specialization, hospital affiliation and
 * medical registration, with a certificate, reviewed before the doctor can
 * add patients (see backend/app/routers/doctor_verification.py).
 */
export default function ProviderProfilePage() {
  const [info, setInfo] = useState(null);
  const [form, setForm] = useState({
    specialty: '', hospital_name: '', registration_number: '', medical_council: '',
    qualification: '', registration_year: '', practice_start_year: '',
  });
  const [education, setEducation] = useState([{ ...EMPTY_EDU }]);
  const [affiliations, setAffiliations] = useState('');
  const [doc, setDoc] = useState(null);
  const [docError, setDocError] = useState('');
  const [certificate, setCertificate] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getMyVerification()
      .then((v) => {
        setInfo(v);
        setForm({
          specialty: v.specialty || '', hospital_name: v.hospital_name || '',
          registration_number: v.registration_number || '', medical_council: v.medical_council || '',
          qualification: v.qualification || '', registration_year: v.registration_year || '',
          practice_start_year: v.practice_start_year || '',
        });
        setEducation(v.education?.length ? v.education.map((e) => ({ ...e, year: e.year || '' })) : [{ ...EMPTY_EDU }]);
        setAffiliations((v.affiliations || []).join('\n'));
      })
      .catch((err) => setError(err.detail || 'Could not load your profile.'));
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSaved(false);
    setSubmitting(true);
    try {
      const v = await api.submitVerification({
        ...form,
        education: JSON.stringify(education.filter((e) => e.degree.trim() || e.institution.trim())),
        affiliations: JSON.stringify(affiliations.split('\n').map((a) => a.trim()).filter(Boolean)),
      }, certificate);
      setInfo(v);
      setDoc(null);
      setCertificate(null);
      setSaved(true);
    } catch (err) {
      setError(err.detail || 'Could not submit your details.');
    } finally {
      setSubmitting(false);
    }
  };

  const setEdu = (i, key) => (e) =>
    setEducation((rows) => rows.map((row, j) => (j === i ? { ...row, [key]: e.target.value } : row)));

  const openDocument = async () => {
    setDocError('');
    try {
      setDoc(await api.getVerificationDocument());
    } catch (err) {
      setDocError(err.detail || 'Could not generate the verification document.');
    }
  };

  if (!info && !error) return <p className="muted">Loading…</p>;
  const status = info?.status || 'not_submitted';

  return (
    <div>
      <div className="page-header no-print">
        <h1>My Profile</h1>
        <p>
          Patients need to know you're a registered doctor. Submit your specialization, hospital affiliation and
          medical registration; a MediPass reviewer checks them against the medical council register and your
          certificate.
        </p>
      </div>

      <div className="surface no-print" style={{ maxWidth: 620, marginBottom: '1.2rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', flexWrap: 'wrap' }}>
          <strong>Verification status:</strong>
          <span className={`verification-status ${status}`}>{STATUS_TEXT[status]}</span>
        </div>
        <p className="muted" style={{ fontSize: '0.85rem', margin: '0.6rem 0 0' }}>
          {status === 'not_submitted' && 'Fill in the form below to get verified.'}
          {status === 'pending' && `Submitted ${parseUtc(info.submitted_at)?.toLocaleString()}. You'll be notified when it's reviewed.`}
          {status === 'verified' && `Verified ${info.reviewed_at ? parseUtc(info.reviewed_at).toLocaleDateString() : ''}. Changing any detail below sends it for review again.`}
          {status === 'rejected' && `Reason: ${info.review_note || 'not given'}. Correct your details and resubmit.`}
          {info?.verification_required && status !== 'verified' && ' Until you are verified you can\'t add new patients.'}
        </p>
        {info?.years_of_experience != null && (
          <p style={{ fontSize: '0.85rem', margin: '0.4rem 0 0' }}>
            <strong>Experience:</strong> {info.years_of_experience} year{info.years_of_experience === 1 ? '' : 's'}
            {' '}(since {info.practice_start_year || info.registration_year})
          </p>
        )}
        {status !== 'not_submitted' && !doc && (
          <button className="btn btn-secondary btn-sm" style={{ marginTop: '0.7rem' }} onClick={openDocument}>
            📄 View verification document
          </button>
        )}
        {docError && <p className="error-text">{docError}</p>}
      </div>

      {doc && (
        <div style={{ marginBottom: '1.2rem' }}>
          <VerificationDocument doc={doc} onClose={() => setDoc(null)} />
        </div>
      )}

      <div className="surface no-print" style={{ maxWidth: 620 }}>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="specialty">Specialization</label>
            <input id="specialty" value={form.specialty} onChange={set('specialty')} required
                   placeholder="e.g. General Physician, Psychiatry, Cardiology" />
          </div>
          <div className="field">
            <label htmlFor="hospitalName">Hospital / clinic affiliation</label>
            <input id="hospitalName" value={form.hospital_name} onChange={set('hospital_name')} required
                   placeholder="Where you practise, as on your letterhead" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0 1rem' }}>
            <div className="field">
              <label htmlFor="regNo">Medical registration number</label>
              <input id="regNo" value={form.registration_number} onChange={set('registration_number')} required
                     placeholder="e.g. KMC 12345" />
            </div>
            <div className="field">
              <label htmlFor="regYear">Year of registration</label>
              <input id="regYear" type="number" min="1950" max={THIS_YEAR}
                     value={form.registration_year} onChange={set('registration_year')} placeholder="e.g. 2012" />
            </div>
          </div>
          <div className="field" style={{ maxWidth: 300 }}>
            <label htmlFor="practiceYear">Practising since (year, optional)</label>
            <input id="practiceYear" type="number" min="1950" max={THIS_YEAR}
                   value={form.practice_start_year} onChange={set('practice_start_year')}
                   placeholder="Defaults to registration year" />
          </div>
          <div className="field">
            <label htmlFor="council">Medical council</label>
            <input id="council" list="councils" value={form.medical_council} onChange={set('medical_council')} required
                   placeholder="Council you are registered with" />
            <datalist id="councils">
              {COUNCILS.map((c) => <option key={c} value={c} />)}
            </datalist>
          </div>
          <div className="field">
            <label htmlFor="qualification">Qualifications</label>
            <input id="qualification" value={form.qualification} onChange={set('qualification')} required
                   placeholder="e.g. MBBS, MD (Psychiatry)" />
          </div>
          <fieldset className="field" style={{ border: 'none', padding: 0, margin: '0 0 1rem' }}>
            <legend style={{ fontWeight: 600, fontSize: '0.88rem', marginBottom: '0.4rem' }}>
              Education history (degree, institution, year)
            </legend>
            {education.map((row, i) => (
              <div key={i} className="education-row">
                <input aria-label={`Degree ${i + 1}`} value={row.degree} onChange={setEdu(i, 'degree')} placeholder="e.g. MBBS" />
                <input aria-label={`Institution ${i + 1}`} value={row.institution} onChange={setEdu(i, 'institution')}
                       placeholder="e.g. AIIMS, New Delhi" />
                <input aria-label={`Year ${i + 1}`} type="number" min="1950" max={THIS_YEAR} value={row.year}
                       onChange={setEdu(i, 'year')} placeholder="Year" />
                <button type="button" className="btn btn-secondary btn-sm" aria-label={`Remove education ${i + 1}`}
                        onClick={() => setEducation((rows) => (rows.length > 1 ? rows.filter((_, j) => j !== i) : [{ ...EMPTY_EDU }]))}>
                  ✕
                </button>
              </div>
            ))}
            {education.length < 10 && (
              <button type="button" className="btn btn-secondary btn-sm"
                      onClick={() => setEducation((rows) => [...rows, { ...EMPTY_EDU }])}>
                + Add degree
              </button>
            )}
          </fieldset>
          <div className="field">
            <label htmlFor="affiliations">Other hospital / institution affiliations (one per line, optional)</label>
            <textarea id="affiliations" rows={2} value={affiliations} onChange={(e) => setAffiliations(e.target.value)}
                      placeholder="e.g. Visiting consultant, Apollo Hospitals" />
          </div>
          <div className="field">
            <label htmlFor="certificate">Registration or degree certificate (PDF or image, max 10 MB)</label>
            <input id="certificate" type="file" accept="application/pdf,image/jpeg,image/png,image/webp"
                   onChange={(e) => setCertificate(e.target.files?.[0] || null)} />
            {info?.certificate_file_name && !certificate && (
              <span className="muted" style={{ fontSize: '0.8rem' }}>
                Current file: {info.certificate_file_name} (upload a new one only if it changed)
              </span>
            )}
          </div>

          {error && <p className="error-text">{error}</p>}
          {saved && <p style={{ color: 'var(--softgreen)', fontWeight: 600 }}>Submitted for review.</p>}

          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Submitting…' : status === 'not_submitted' ? 'Submit for verification' : 'Save and resubmit'}
          </button>
        </form>
      </div>
    </div>
  );
}
