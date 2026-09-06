#!/usr/bin/env python3
"""Extract text from a PDF: poppler text-layer first, tesseract OCR fallback.

The same two-stage approach the GA executive-orders enricher uses
(scripts/enrich_ga_executive_orders.py): `pdftotext` pulls an embedded text layer
almost instantly for the machine-generated PDFs most agendas are; only a scanned,
image-only document (little or no text layer) falls back to rasterising each page
with `pdftoppm` and running Tesseract. Both tools are optional — where poppler /
Tesseract are absent (a dev laptop) the functions degrade to '' and the caller
carries on, so nothing here is a hard dependency. CI installs poppler-utils +
tesseract-ocr for the OCR path.

Factored into lib/ so more than one enricher can share one implementation; the EO
enricher predates it and keeps its own copy for now.
"""

import os
import shutil
import subprocess

# Below this many characters, assume pdftotext found no real text layer and fall
# back to OCR.
MIN_TEXT_CHARS = 200

# Guardrails so a pathological PDF can't stall a batch. OCR is the slow path
# (rasterise + Tesseract per page at 300 DPI), so cap the pages we OCR; a huge
# machine-generated agenda still extracts fully via the fast pdftotext path.
_OCR_MAX_PAGES = 30
_PDFTOTEXT_TIMEOUT = 120
_PDFTOPPM_TIMEOUT = 300
_TESSERACT_TIMEOUT = 180


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def has_ocr():
    """True when the OCR fallback (pdftoppm + tesseract) is actually available."""
    return bool(shutil.which('pdftoppm') and shutil.which('tesseract'))


def pdftotext(pdf_path):
    """Extract an embedded text layer with poppler. '' if unavailable/empty."""
    if not shutil.which('pdftotext'):
        return ''
    try:
        proc = _run(['pdftotext', '-layout', '-nopgbrk', pdf_path, '-'], _PDFTOTEXT_TIMEOUT)
        if proc.returncode == 0:
            return proc.stdout.decode('utf-8', errors='replace').strip()
        print('    pdftotext exit %s' % proc.returncode)
    except Exception as exc:  # noqa: BLE001
        print('    pdftotext failed: %s' % exc)
    return ''


def ocr_pdf(pdf_path, workdir):
    """Rasterise with pdftoppm and OCR each page with Tesseract. '' if unavailable."""
    if not has_ocr():
        return ''
    try:
        prefix = os.path.join(workdir, 'page')
        proc = _run(['pdftoppm', '-r', '300', '-png', '-l', str(_OCR_MAX_PAGES),
                     pdf_path, prefix], _PDFTOPPM_TIMEOUT)
        if proc.returncode != 0:
            print('    pdftoppm exit %s' % proc.returncode)
            return ''
        pages = sorted(f for f in os.listdir(workdir)
                       if f.startswith('page') and f.endswith('.png'))
        chunks = []
        for pg in pages:
            r = _run(['tesseract', os.path.join(workdir, pg), 'stdout'], _TESSERACT_TIMEOUT)
            if r.returncode == 0:
                chunks.append(r.stdout.decode('utf-8', errors='replace'))
        return '\n'.join(chunks).strip()
    except Exception as exc:  # noqa: BLE001
        print('    OCR failed: %s' % exc)
    return ''


def extract_text(pdf_path):
    """Best text available: pdftotext, then OCR fallback. Returns (text, method).

    method is 'pdftotext', 'ocr', or 'none'. `pdf_path` points at a PDF already on
    disk (the caller owns the temp file / cleanup).
    """
    text = pdftotext(pdf_path)
    if len(text) >= MIN_TEXT_CHARS:
        return text, 'pdftotext'
    workdir = os.path.dirname(pdf_path)
    ocr = ocr_pdf(pdf_path, workdir)
    if len(ocr) > len(text):
        return ocr, 'ocr'
    return text, ('pdftotext' if text else 'none')
