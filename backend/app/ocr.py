"""
Real OCR pipeline.

- Images (jpg/png/etc): run through Tesseract, which gives us genuine
  per-word confidence scores (0-100) -- these are real signal from the OCR
  engine, not a guess, and drive the confidence shown during verification.
- PDFs: try direct text extraction first (PyMuPDF) -- most lab reports and
  reports exported as PDF already have embedded text, so this
  is instant and 100% accurate, no OCR needed. Only if a PDF page has no
  extractable text (i.e. it's a scanned image saved as PDF) do we render
  that page to an image and run it through Tesseract, same as a photo.

Requires the Tesseract OCR engine to be installed on the machine running
the backend (this is a separate system install, not a pip package -- see
README "Installing Tesseract" for platform-specific instructions). If it's
missing, we raise a clear, actionable error instead of a stack trace.
"""
import io
from dataclasses import dataclass
from typing import List

import os
import pytesseract
# Let pytesseract auto-discover tesseract on PATH.  For local Windows dev,
# set TESSERACT_CMD_PATH in .env to override (e.g. "C:\Program Files\Tesseract-OCR\tesseract.exe").
_tesseract_override = os.environ.get("TESSERACT_CMD_PATH")
if _tesseract_override:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_override
from PIL import Image
import pymupdf


class OCRUnavailableError(RuntimeError):
    """Raised when the Tesseract engine itself isn't installed/found."""
    pass


@dataclass
class OCRLine:
    text: str
    confidence: float  # 0.0-1.0


def _ocr_image(image: Image.Image) -> List[OCRLine]:
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        raise OCRUnavailableError(
            "The Tesseract OCR engine isn't installed or isn't on PATH. "
            "See backend/README.md 'Installing Tesseract' for setup steps."
        ) from e

    # group words back into lines using tesseract's block/par/line numbering
    lines: dict[tuple, list] = {}
    for i in range(len(data["text"])):
        word = data["text"][i].strip()
        conf = int(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((word, conf))

    results = []
    for key in sorted(lines.keys()):
        words = lines[key]
        text = " ".join(w for w, _ in words)
        avg_conf = sum(c for _, c in words) / len(words) / 100.0
        results.append(OCRLine(text=text, confidence=round(avg_conf, 3)))
    return results


def _pdf_page_to_image(page: "pymupdf.Page", zoom: float = 2.0) -> Image.Image:
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def run_ocr(file_bytes: bytes, content_type: str, file_name: str) -> List[OCRLine]:
    """
    Returns a list of OCRLine (text + confidence 0.0-1.0), one per detected
    line, in reading order. Confidence is 1.0 for text pulled directly from
    a PDF's embedded text layer (no OCR uncertainty involved).
    """
    is_pdf = content_type == "application/pdf" or file_name.lower().endswith(".pdf")

    if is_pdf:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        try:
            all_lines: List[OCRLine] = []
            for page in doc:
                embedded_text = page.get_text().strip()
                if embedded_text:
                    for raw_line in embedded_text.splitlines():
                        line = raw_line.strip()
                        if line:
                            all_lines.append(OCRLine(text=line, confidence=1.0))
                else:
                    # scanned page with no text layer -- fall back to OCR
                    image = _pdf_page_to_image(page)
                    all_lines.extend(_ocr_image(image))
            return all_lines
        finally:
            doc.close()

    # plain image upload
    image = Image.open(io.BytesIO(file_bytes))
    return _ocr_image(image)
