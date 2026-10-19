#!/usr/bin/env python3
"""Two guards against silently reading LESS of a document than we once did.

Both were found by running the offline re-tag against the real corpus, and both
look the same from the outside: the same meeting, the same URL, fewer characters,
and tags quietly disappearing.

  1. HYBRID PDFs (lib/pdf_text.py). extract_text used one document-level floor:
     200 characters of text layer and the PDF was accepted whole. A packet whose
     body is scanned images but which carries one machine-generated page clears
     that easily, so the scanned body — the actual agenda items — was never OCR'd.
     Real case: a Paulding agenda read 7,352 characters from its text layer where
     OCR of the same PDF had found 11,884, and the rezoning and variance items
     lived only in the skipped part. The decision is now also per page.

  2. TEXT REGRESSION (lib/enrich_runner.py). A Granicus viewer serves the printed
     2-page agenda PDF for some meetings and the much richer HTML agenda for
     others, at the same URL (Barrow: 16 html / 24 pdf in one window). barrow/1154
     went 49,960 -> 7,137 characters between runs. The enrichers now keep the
     richer earlier reading rather than publishing the worse one.

Run: python scripts/test_pdf_hybrid_and_regression.py   (no network, no repo writes)
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import pdf_text  # noqa: E402
from lib.enrich_runner import text_regressed  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


# ── 1. hybrid-page detection ─────────────────────────────────────────────────
# mostly_empty_pages() is the whole decision, and it is pure, so it is pinned
# directly rather than only through a PDF.
BODY = 'Rezoning application for parcel 12-345 with a variance request. ' * 3
check('a normal multi-page document is not hybrid',
      pdf_text.mostly_empty_pages([BODY, BODY, BODY]), False)
check('one text page before a scanned body IS hybrid',
      pdf_text.mostly_empty_pages([BODY, '', '', '', '']), True)
check('half-empty is not over the threshold',
      pdf_text.mostly_empty_pages([BODY, BODY, '', '']), False)
check('a trailing form-feed empty is not counted as a page',
      pdf_text.mostly_empty_pages([BODY, BODY, '']), False)
check('a single short page is a short document, not a scanned body',
      pdf_text.mostly_empty_pages(['Agenda.']), False)
check('a single short page plus trailing break is still not hybrid',
      pdf_text.mostly_empty_pages(['Agenda.', '']), False)
check('pages of whitespace-only count as empty',
      pdf_text.mostly_empty_pages([BODY, '   \n  ', '\n', '  ']), True)
check('no pages at all is not hybrid', pdf_text.mostly_empty_pages([]), False)
# A page with a scanning artefact (a stray header) is still effectively empty.
check('a near-empty page is empty below MIN_PAGE_CHARS',
      pdf_text.mostly_empty_pages([BODY, 'Page 2', 'Page 3', 'Page 4']), True)


# ── 2. the same decision through a REAL pdf ──────────────────────────────────
# Built here with poppler's own tooling absent, so the PDF is written by hand:
# one page carrying a text object, the rest carrying none — which is exactly what
# pdftotext sees for a scanned page.
def _pdf(pages_text):
    """A minimal multi-page PDF; a page whose entry is '' gets no text object."""
    objs, kids = [], []
    for i, txt in enumerate(pages_text):
        pid, cid = 4 + i * 2, 5 + i * 2
        kids.append('%d 0 R' % pid)
        stream = ''
        if txt:
            esc = txt.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
            stream = 'BT /F1 11 Tf 40 700 Td (%s) Tj ET' % esc
        objs.append((pid, '<< /Type /Page /Parent 3 0 R /MediaBox [0 0 612 792] '
                          '/Resources << /Font << /F1 2 0 R >> >> /Contents %d 0 R >>'
                          % cid))
        objs.append((cid, '<< /Length %d >>\nstream\n%s\nendstream' % (len(stream), stream)))
    head = [(1, '<< /Type /Catalog /Pages 3 0 R >>'),
            (2, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'),
            (3, '<< /Type /Pages /Kids [%s] /Count %d >>' % (' '.join(kids), len(pages_text)))]
    out = b'%PDF-1.4\n'
    offsets = {}
    for num, body in head + objs:
        offsets[num] = len(out)
        out += ('%d 0 obj\n%s\nendobj\n' % (num, body)).encode('latin-1')
    xref = len(out)
    n = max(offsets) + 1
    out += ('xref\n0 %d\n0000000000 65535 f \n' % n).encode()
    for i in range(1, n):
        out += ('%010d 00000 n \n' % offsets.get(i, 0)).encode()
    out += ('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
            % (n, xref)).encode()
    return out


if not shutil.which('pdftotext'):
    print('  note: pdftotext not installed — skipping the real-PDF checks')
else:
    tmp = tempfile.mkdtemp(prefix='votega-hybrid-test-')
    try:
        # Long enough that a 3-page document clears MIN_TEXT_CHARS; otherwise the
        # fixture would go to OCR for being SHORT, not for being hybrid, and the
        # test would pass for the wrong reason.
        long_line = ('Rezoning application for parcel 12-345 with a variance '
                     'request and a special land use permit before the board')
        # A normal document: every page carries text.
        normal = os.path.join(tmp, 'normal.pdf')
        with open(normal, 'wb') as fh:
            fh.write(_pdf([long_line, long_line, long_line]))
        pages = pdf_text.pdftotext_pages(normal)
        check('real pdf: pages are split on the form feed', len(pages) >= 3, True)
        check('real pdf: a fully-texted document is not hybrid',
              pdf_text.mostly_empty_pages(pages), False)
        check('real pdf: pdftotext() still returns one joined string',
              long_line in pdf_text.pdftotext(normal), True)

        # The hybrid: one cover page of text, four pages with no text object.
        hybrid = os.path.join(tmp, 'hybrid.pdf')
        with open(hybrid, 'wb') as fh:
            fh.write(_pdf([long_line, '', '', '', '']))
        hpages = pdf_text.pdftotext_pages(hybrid)
        check('real pdf: a cover page over a blank body IS hybrid',
              pdf_text.mostly_empty_pages(hpages), True)

        # extract_text must TRY ocr on the hybrid and NOT on the normal document.
        tried = []
        real_ocr = pdf_text.ocr_pdf
        pdf_text.ocr_pdf = lambda p, w: (tried.append(os.path.basename(p)) or '')
        try:
            t1, m1 = pdf_text.extract_text(normal)
            t2, m2 = pdf_text.extract_text(hybrid)
        finally:
            pdf_text.ocr_pdf = real_ocr
        check('extract_text does not OCR a healthy document', 'normal.pdf' in tried, False)
        check('extract_text OCRs the hybrid', 'hybrid.pdf' in tried, True)
        check('healthy document keeps the pdftotext method', m1, 'pdftotext')
        # With OCR stubbed to '' (as on a machine without tesseract), the thin text
        # layer is kept rather than lost: a partial read beats no read.
        check('hybrid keeps its partial text when OCR is unavailable',
              long_line in t2, True)
        check('hybrid labelled by where the text actually came from', m2, 'pdftotext')

        # And when OCR works, its longer text wins.
        pdf_text.ocr_pdf = lambda p, w: 'OCR TEXT ' * 200
        try:
            t3, m3 = pdf_text.extract_text(hybrid)
        finally:
            pdf_text.ocr_pdf = real_ocr
        check('hybrid prefers OCR when it reads more', m3, 'ocr')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 3. text-regression guard ─────────────────────────────────────────────────
# The real Paulding record: a hybrid PDF whose thin text layer dropped two
# land-use findings that the earlier OCR had supported.
TAGGED = {'tags': ['rezoning', 'variance', 'contract'], 'textChars': 11884,
          'textMethod': 'ocr'}

check('the real Paulding case is a regression',
      text_regressed('p1', TAGGED, 7352, 'pdftotext', ['contract']), True)
check('a slightly shorter agenda is NOT a regression',
      text_regressed('p1', TAGGED, 11000, 'pdftotext', ['contract']), False)
check('exactly at the threshold is not a regression',
      text_regressed('p1', dict(TAGGED, textChars=10000), 6700, 'pdftotext', []), False)
check('just under the threshold is a regression',
      text_regressed('p1', dict(TAGGED, textChars=10000), 6600, 'pdftotext', []), True)
check('a longer re-read is never a regression',
      text_regressed('p1', TAGGED, 20000, 'ocr', []), False)

# THE BARROW CASE, which is why the test is lost FINDINGS and not lost characters.
# That viewer answers some meetings with a JS shell stripping to ~50k characters
# that match nothing; the much shorter PDF reading of the same meeting is the real
# agenda. A character-count guard would have preserved the garbage.
check('a shorter reading that matched MORE is not a regression',
      text_regressed('1154', {'tags': [], 'textChars': 49960, 'textMethod': 'html'},
                     7137, 'pdftotext',
                     ['alpr', 'appointment', 'contract', 'millage-budget']), False)
check('a shorter reading that keeps every prior finding is not a regression',
      text_regressed('x', TAGGED, 1000, 'pdftotext',
                     ['rezoning', 'variance', 'contract', 'alpr']), False)
check('a shorter reading that keeps exactly the prior findings is not a regression',
      text_regressed('x', TAGGED, 1000, 'pdftotext',
                     ['rezoning', 'variance', 'contract']), False)
check('dropping even one prior finding is a regression',
      text_regressed('x', TAGGED, 1000, 'pdftotext', ['rezoning', 'contract']), True)

# A prior record with nothing to lose must never block a fresh reading.
check('no prior record, no regression',
      text_regressed('p1', None, 10, 'pdftotext', []), False)
check('prior record with no tags does not block',
      text_regressed('p1', {'tags': [], 'textChars': 50000}, 10, 'pdftotext', []), False)
check('prior record with no textChars does not block',
      text_regressed('p1', {'tags': ['rezoning']}, 10, 'pdftotext', []), False)
# Callers that pass no tags fall back to the length test alone, so the guard still
# protects an enricher that has not been updated to classify first.
check('omitting new_tags keeps the length-only behaviour',
      text_regressed('p1', TAGGED, 100, 'pdftotext'), True)

if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All hybrid-PDF and text-regression checks passed.')
