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

# HYBRID PDFs. The document-level floor above is not enough on its own: a packet
# whose body is scanned images but which carries ONE machine-generated page (a
# cover sheet, a header, a generated index) clears 200 characters easily, so the
# whole document was accepted from its text layer and the scanned body — usually
# the actual agenda items — was never OCR'd. A real case: a Paulding agenda read
# 7,352 characters as a text layer where OCR of the same PDF had previously found
# 11,884, and the rezoning and variance items lived only in the part that was
# skipped. So the decision is also made PER PAGE: when most pages yield almost
# nothing, the text layer is not representative of the document and OCR is tried.
MIN_PAGE_CHARS = 60        # a page below this is treated as having no text layer
MAX_EMPTY_PAGE_RATIO = 0.5  # more than half such pages -> suspect a scanned body

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


def pdftotext_pages(pdf_path):
    """The text layer as a LIST OF PAGES. [] if poppler is unavailable or it failed.

    Page breaks are kept (no -nopgbrk) purely so the caller can see the per-page
    distribution; joining the result reproduces what the old single-string call
    returned.
    """
    if not shutil.which('pdftotext'):
        return []
    try:
        proc = _run(['pdftotext', '-layout', pdf_path, '-'], _PDFTOTEXT_TIMEOUT)
        if proc.returncode == 0:
            out = proc.stdout.decode('utf-8', errors='replace')
            return out.split('\f')
        print('    pdftotext exit %s' % proc.returncode)
    except Exception as exc:  # noqa: BLE001
        print('    pdftotext failed: %s' % exc)
    return []


def pdftotext(pdf_path):
    """Extract an embedded text layer with poppler. '' if unavailable/empty."""
    return '\n'.join(pdftotext_pages(pdf_path)).strip()


def mostly_empty_pages(pages):
    """True when most pages carry almost no text — the hybrid-PDF signal.

    A trailing empty element from the final page break is not a page, and a
    single-page document is never judged this way: one short page is a short
    document, not a scanned body.
    """
    npages = len(pages)
    # Drop a trailing '' produced by the final form feed.
    if pages and not pages[-1].strip():
        npages -= 1
    if npages < 2:
        return False
    empty = sum(1 for p in pages[:npages] if len(p.strip()) < MIN_PAGE_CHARS)
    return empty > npages * MAX_EMPTY_PAGE_RATIO


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
    pages = pdftotext_pages(pdf_path)
    text = '\n'.join(pages).strip()
    # Accept the text layer only when it is both long enough overall AND spread
    # across the document. A hybrid PDF fails the second test, so it goes to OCR
    # like any other scanned document.
    if len(text) >= MIN_TEXT_CHARS and not mostly_empty_pages(pages):
        return text, 'pdftotext'
    workdir = os.path.dirname(pdf_path)
    ocr = ocr_pdf(pdf_path, workdir)
    # Longer wins: on a hybrid, OCR reads the scanned body AND re-reads the
    # machine-generated page, so it should come back longer. Where OCR is
    # unavailable (no tesseract) it returns '' and the text layer is kept — a
    # partial read beats no read, and the method label still says where it came
    # from.
    if len(ocr) > len(text):
        return ocr, 'ocr'
    return text, ('pdftotext' if text else 'none')
