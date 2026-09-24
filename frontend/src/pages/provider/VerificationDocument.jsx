import { parseUtc } from '../../grants';

const OVERALL_CLASS = {
  Compliant: 'Compliant',
  'Pending review': 'Pending',
  'Not compliant': 'Not',
  'Not submitted': 'Not',
};

function when(value) {
  const d = parseUtc(value);
  return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}

function Row({ label, children }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{children || '—'}</td>
    </tr>
  );
}

/**
 * Printable doctor verification document (data from
 * GET /doctor-verification/document). "Print / Save as PDF" uses the
 * browser's print dialog; print CSS hides the rest of the app.
 */
export default function VerificationDocument({ doc, onClose }) {
  const { credentials: c, verification: v, experience: x, compliance } = doc;

  return (
    <div>
      <div className="no-print" style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.8rem' }}>
        <button className="btn btn-primary btn-sm" onClick={() => window.print()}>Print / Save as PDF</button>
        <button className="btn btn-secondary btn-sm" onClick={onClose}>Close document</button>
      </div>

      <article className="verif-doc" aria-label="Doctor verification document">
        <header className="verif-doc-head">
          <div>
            <h2>Doctor Profile Verification</h2>
            <div style={{ fontSize: '1.05rem', fontWeight: 600, marginTop: '0.3rem' }}>{doc.doctor.name}</div>
            <div className="muted" style={{ fontSize: '0.85rem' }}>{doc.doctor.email}</div>
          </div>
          <div className="verif-doc-meta">
            <div>Document {doc.document_id || '—'}</div>
            <div>Generated {when(doc.generated_at)}</div>
            <div style={{ marginTop: '0.4rem' }}>
              <span className={`compliance-overall ${OVERALL_CLASS[compliance.overall] || 'Not'}`}>
                {compliance.overall}
              </span>
            </div>
          </div>
        </header>

        <section>
          <h3>1. Credentials and licence</h3>
          <table>
            <tbody>
              <Row label="Licence / registration status">{c.license_status}</Row>
              <Row label="Registration number">{c.registration_number}</Row>
              <Row label="Medical council">{c.medical_council}</Row>
              <Row label="Year of registration">{c.registration_year}</Row>
              <Row label="Qualifications">{c.qualification}</Row>
              <Row label="Certificate on file">{c.certificate_file_name}</Row>
            </tbody>
          </table>
        </section>

        <section>
          <h3>2. Education</h3>
          {doc.education.length === 0 ? (
            <p className="muted" style={{ fontSize: '0.88rem', margin: 0 }}>No education history provided.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Degree</th><th>Institution</th><th>Year</th></tr>
              </thead>
              <tbody>
                {doc.education.map((e, i) => (
                  <tr key={i}><td>{e.degree}</td><td>{e.institution}</td><td>{e.year || '—'}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section>
          <h3>3. Specialization, affiliations and experience</h3>
          <table>
            <tbody>
              <Row label="Specialization">{doc.specialization}</Row>
              <Row label="Primary hospital / clinic">{doc.affiliations.primary}</Row>
              <Row label="Other affiliations">{doc.affiliations.other.join('; ')}</Row>
              <Row label="Years of experience">
                {x.years != null && `${x.years} year${x.years === 1 ? '' : 's'} (since ${x.since}, from ${x.since_basis})`}
              </Row>
            </tbody>
          </table>
        </section>

        <section>
          <h3>4. Verification record</h3>
          <table>
            <tbody>
              <Row label="Submitted for review">{when(v.submitted_at)}</Row>
              <Row label="Reviewed">{v.reviewed_at ? when(v.reviewed_at) : 'Not yet reviewed'}</Row>
              <Row label="Reviewed by">{v.reviewer}</Row>
              <Row label="Reviewer's note">{v.review_note}</Row>
              <Row label="Approval authority">{v.authority}</Row>
            </tbody>
          </table>
        </section>

        <section>
          <h3>5. Medical board compliance</h3>
          <table>
            <thead>
              <tr><th>Requirement</th><th>Result</th><th>Details</th></tr>
            </thead>
            <tbody>
              {compliance.checks.map((chk) => (
                <tr key={chk.label}>
                  <td>{chk.label}{!chk.required && ' (recommended)'}</td>
                  <td>
                    {chk.passed
                      ? <span className="check-pass">✓ Met</span>
                      : <span className={chk.required ? 'check-fail' : 'check-optional'}>✗ Not met</span>}
                  </td>
                  <td>{chk.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <footer className="verif-doc-foot">
          Generated by MediPass from the details the doctor submitted and the reviewer's decision. MediPass has no
          automatic link to the National Medical Commission; the registration was checked by the reviewer named
          above. Any change to these details sends the profile back for review.
        </footer>
      </article>
    </div>
  );
}
