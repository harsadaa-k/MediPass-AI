import { useState, useRef, useEffect } from 'react';
import { api } from '../../api';
import ViewSourceButton from '../../components/ViewSourceButton';

// Cosmetic progress stages shown while the single upload request runs.
// The backend does all of this in one call, so we advance on a timer and
// hold on the last stage until the response comes back.
const UPLOAD_STAGES = ['Uploading…', 'Analyzing…', 'Extracting…', 'Checking confidence…'];
const STAGE_INTERVAL_MS = 2000;

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'application/pdf', 'application/dicom'];
// Browsers usually report .dcm files with an empty or generic type.
const isDicomFile = (f) => /\.(dcm|dicom)$/i.test(f.name) || f.type === 'application/dicom';

export default function UploadDocument({ onUploaded }) {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [documentType, setDocumentType] = useState('prescription');
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [duplicate, setDuplicate] = useState(null); // 409 "already uploaded this file"
  const [submitting, setSubmitting] = useState(false);
  const [stage, setStage] = useState(0);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!submitting) return undefined;
    const timer = setInterval(() => {
      setStage((s) => Math.min(s + 1, UPLOAD_STAGES.length - 1));
    }, STAGE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [submitting]);

  // Shared by the file input (browse / camera) and the drop zone.
  const selectFile = (selected) => {
    setResult(null);
    setError('');
    setDuplicate(null);
    if (!selected) {
      setFile(null);
      setPreviewUrl(null);
      return;
    }
    setFile(selected);
    if (isDicomFile(selected)) setDocumentType('lab_report'); // medical images are lab reports
    if (selected.type.startsWith('image/')) {
      setPreviewUrl(URL.createObjectURL(selected));
    } else {
      setPreviewUrl(null); // PDFs: no inline preview, just show the filename
    }
  };

  const handleFileChange = (e) => selectFile(e.target.files?.[0]);

  const handleDragOver = (e) => {
    e.preventDefault();
    if (!submitting) setDragging(true);
  };

  const handleDragLeave = (e) => {
    // ignore leave events fired when moving between child elements
    if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (submitting) return;
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    if (!ACCEPTED_TYPES.includes(dropped.type) && !isDicomFile(dropped)) {
      setError('That file type isn\'t supported. Drop a JPEG, PNG, WEBP, PDF or DICOM (.dcm) file.');
      return;
    }
    if (inputRef.current) inputRef.current.value = '';
    selectFile(dropped);
  };

  const reset = () => {
    setFile(null);
    setPreviewUrl(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleSubmit = async (e, allowDuplicate = false) => {
    e?.preventDefault();
    if (!file) {
      setError('Choose a photo or file first.');
      return;
    }
    setError('');
    setResult(null);
    setDuplicate(null);
    setStage(0);
    setSubmitting(true);
    try {
      const doc = await api.uploadDocument(file, documentType, allowDuplicate);
      setResult(doc);
      reset();
      if (onUploaded) onUploaded();
    } catch (err) {
      if (err.detail?.code === 'duplicate_upload') {
        setDuplicate(err.detail);
      } else {
        setError(typeof err.detail === 'string' ? err.detail : 'Upload failed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Upload a document</h1>
        <p>
          Take a photo of a prescription or lab report, upload an X-ray, or choose a file. MediPass
          reads it and pulls out structured entries for you to check before they join your timeline.
        </p>
      </div>

      <div className="surface" style={{ maxWidth: 560 }}>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="fileInput">Photo or file</label>
            <div
              className={`dropzone ${dragging ? 'is-dragging' : ''}`}
              onDragOver={handleDragOver}
              onDragEnter={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className="dropzone-title">
                {dragging ? 'Drop to select this file' : 'Drag & drop a file here, or'}
              </div>
              <input
                id="fileInput"
                ref={inputRef}
                type="file"
                accept="image/*,application/pdf,.dcm,application/dicom"
                capture="environment"
                onChange={handleFileChange}
                disabled={submitting}
              />
            </div>
            <span className="muted" style={{ fontSize: '0.8rem' }}>
              JPEG, PNG, WEBP, PDF or DICOM (.dcm), up to 15 MB. On a phone this opens your camera.
            </span>
          </div>

          {previewUrl && (
            <img
              src={previewUrl}
              alt="Selected document preview"
              style={{ maxWidth: '100%', maxHeight: 240, borderRadius: 'var(--radius)', border: '1px solid var(--border)', marginBottom: '0.9rem' }}
            />
          )}
          {file && !previewUrl && (
            <p className="muted" style={{ fontSize: '0.85rem' }}>Selected: {file.name}</p>
          )}

          <div className="field">
            <label htmlFor="documentType">Document type</label>
            <select
              id="documentType"
              value={documentType}
              onChange={(e) => setDocumentType(e.target.value)}
              disabled={submitting}
            >
              <option value="prescription">Prescription</option>
              <option value="lab_report">Lab report</option>
            </select>
            <span className="muted" style={{ fontSize: '0.8rem' }}>
              X-ray and scan images count as a lab report. You'll confirm the body part before it's saved.
            </span>
          </div>

          {error && <p className="error-text">{error}</p>}

          {duplicate && (
            <div className="duplicate-note" role="alert">
              <span>⚠ {duplicate.message}</span>
              <ViewSourceButton documentId={duplicate.document_id} />
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleSubmit(null, true)}>
                Upload anyway
              </button>
            </div>
          )}

          <button type="submit" className="btn btn-primary" disabled={submitting || !file}>
            {submitting ? UPLOAD_STAGES[stage] : 'Upload document'}
          </button>

          {submitting && (
            <ol className="upload-stages" aria-live="polite">
              {UPLOAD_STAGES.map((label, i) => {
                const state = i < stage ? 'is-done' : i === stage ? 'is-active' : '';
                return (
                  <li key={label} className={`upload-stage ${state}`}>
                    <span className="upload-stage-icon">
                      {i < stage ? '✓' : i === stage ? <span className="voice-spinner" style={{ display: 'inline-block', width: 14, height: 14 }} /> : '•'}
                    </span>
                    {label.replace('…', '')}
                  </li>
                );
              })}
            </ol>
          )}
        </form>

        {result && (
          <div style={{ marginTop: '1rem' }}>
            <p style={{ color: 'var(--softgreen)', fontWeight: 600, marginBottom: '0.2rem' }}>
              Uploaded "{result.file_name}".
            </p>
            <p className="muted" style={{ fontSize: '0.86rem' }}>
              Detected as <strong>{result.document_type.replace('_', ' ')}</strong>. Go to
              Verify records to check what was extracted.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
