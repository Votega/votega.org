#!/usr/bin/env python3
"""Measure a candidate ALPR keyword set against real agenda/minutes PDFs.

A DIAGNOSTIC, not part of the build. It answers the question that has to be
settled before an `alpr` subject goes into lib/meeting_topics.py: does a
vendor-aware keyword set actually catch license-plate-reader discussions in the
wild, and how often does it fire on meetings that have nothing to do with ALPR?

It reuses the production extraction path — lib.http.fetch_bytes + the same
_PDF_HEADERS as enrich_ocr_meetings.py, then lib.pdf_text.extract_text (poppler
text layer, Tesseract OCR fallback) — so a green run here means the same text
the enricher would see. Nothing is written; text is classified and discarded.

Two corpora:
  KNOWN_ALPR  hand-verified positives (Flock votes/contracts from
              flock-covington.md). Every one SHOULD match → recall.
  Control     a sample of recent meetings pulled from the committed
              local-*-meetings.json sidecars. Most SHOULD be clean → any hit is
              a candidate false positive to eyeball (the script prints which
              phrase fired so you can judge).

Usage:
    python scripts/probe_alpr_keywords.py                 # default control sample
    python scripts/probe_alpr_keywords.py --control 12    # wider control net
    python scripts/probe_alpr_keywords.py --slugs newton,fulton,cobb

Needs network + poppler (pdftotext); OCR fallback also needs tesseract. Intended
for an open-network environment (local dev or CI) — the web sandbox blocks .gov
egress, so fetches there fail with a proxy 403, which is not a keyword result.
"""

import argparse
import glob
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from lib.http import fetch_bytes  # noqa: E402
from lib.pdf_text import extract_text, has_ocr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'assets', 'data')

_PDF_HEADERS = {
    'User-Agent': 'votega.org/1.0 (alpr-keyword-probe)',
    'Accept':     'application/pdf',
}

# ── Candidate ALPR taxonomy ────────────────────────────────────────────────────
# Two layers. GENERIC is the recall net: even an unknown vendor's contract almost
# always contains one of these phrases, so it catches vendors we've never heard
# of. VENDORS adds attribution.
#
# First real run (recall 1/3) proved the generic net alone under-matches: agenda/
# minutes language calls the company plain "Flock" and its product "cameras", not
# "license plate reader" — so bare `flock` is REQUIRED for recall. It carries a
# false-positive risk ("a flock of geese"), so matching is word-boundary (\bflock\b
# skips "flocking"/"flocked") and the probe prints context around every hint word
# so real FPs are caught by eye. Still-omitted ambiguous tokens: bare ' lpr '
# (many acronyms) and lone vendor surnames like 'leonardo'.
ALPR_KEYWORDS = {
    # Generic capability language — the workhorse.
    'license plate reader':        'generic',
    'license plate recognition':   'generic',
    'automated license plate':     'generic',
    'automatic license plate':     'generic',
    'plate reader':                'generic',
    'lpr camera':                  'generic',
    'alpr':                        'generic',
    # Flock — bare token, because that is how agendas name it.
    'flock':                       'flock',
    # Vendors beyond Flock — ALPR-specific brands only. The bare 'motorola
    # solutions' parent brand, 'mobile-vision' (in-car video) and 'fusus' (Axon
    # RTCC camera aggregator) over-matched non-ALPR contracts in a real run, so
    # they are omitted; 'vigilant solutions' is Motorola's actual ALPR line.
    'vigilant solutions':          'motorola',
    'genetec':                     'genetec',
    'autovu':                      'genetec',
    'sharpv':                      'genetec',
    'rekor':                       'rekor',
    'openalpr':                    'rekor',
    'elsag':                       'leonardo',
    'neology':                     'neology',
    'jenoptik':                    'jenoptik',
    'perceptics':                  'perceptics',
    'verra mobility':              'verra',
    'platesmart':                  'platesmart',
}

# Compiled word-boundary matchers — \b so 'flock' skips 'flocking', 'alpr' skips
# larger tokens, and multi-word phrases still match across single spaces.
_MATCHERS = {p: re.compile(r'\b' + re.escape(p) + r'\b') for p in ALPR_KEYWORDS}

# Diagnostic only: words that HINT at surveillance without being keywords, so a
# missed known-ALPR doc reveals the actual vocabulary to add. Not used to tag.
HINT_WORDS = ['flock', 'license plate', 'plate reader', 'lpr', 'alpr', 'camera',
              'surveillance', 'safer city', 'safe city', 'real-time crime',
              'security camera', 'genetec', 'rekor', 'motorola', 'vigilant']


def classify(text):
    """Return {vendor_tag: [phrases]} for every keyword present (word-boundary)."""
    t = (text or '').lower()
    hits = {}
    for phrase, tag in ALPR_KEYWORDS.items():
        if _MATCHERS[phrase].search(t):
            hits.setdefault(tag, []).append(phrase)
    return hits


def hint_context(text, width=55, cap=6):
    """Short snippets around HINT_WORDS — shows the raw language near a hint so we
    can see WHY a doc matched or missed and what phrasing to add. Deduped, capped."""
    t = (text or '').lower()
    seen = set()
    out = []
    for w in HINT_WORDS:
        i = t.find(w)
        if i < 0:
            continue
        a = max(0, i - width)
        b = min(len(t), i + len(w) + width)
        snip = ' '.join(t[a:b].split())
        if snip in seen:
            continue
        seen.add(snip)
        out.append('%-14s …%s…' % (w, snip))
        if len(out) >= cap:
            break
    return out


def get_text(url):
    pdf = fetch_bytes(url, headers=_PDF_HEADERS, retries=2, backoff=3, label=url)
    if pdf is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'doc.pdf')
        with open(path, 'wb') as f:
            f.write(pdf)
        text, method = extract_text(path)
    return text, method


# Hand-verified positives from flock-covington.md (Flock votes / contracts).
KNOWN_ALPR = [
    ('Newton BOC 2025-04-15 agenda (item #18, Flock)',
     'https://www.newtoncountyga.gov/AgendaCenter/ViewFile/Agenda/_04152025-812'),
    ('Covington City Council 2025-12-15 minutes (item #11, Flock contract)',
     'https://cityofcovington.org/ckeditorfiles/files/2025_CityCouncil_1215_Minutes.pdf'),
    ('Covington City Council 2026-06-15 minutes (item #9, Safer City 10-yr)',
     'https://cityofcovington.org/ckeditorfiles/files/2026_CityCouncil_0615_Minutes.pdf'),
]


def control_docs(slugs, per_place):
    """Recent meetings pulled from committed sidecars — expected mostly clean."""
    out = []
    files = []
    if slugs:
        for s in slugs:
            files += glob.glob(os.path.join(DATA_DIR, 'local-%s-meetings.json' % s))
    else:
        files = sorted(glob.glob(os.path.join(DATA_DIR, 'local-*-meetings.json')))
        files = [f for f in files if not f.endswith('-enriched.json')]
    for f in files:
        try:
            doc = json.load(open(f, encoding='utf-8'))
        except (ValueError, OSError):
            continue
        place = (doc.get('metadata') or {}).get('place') or os.path.basename(f)
        n = 0
        for m in doc.get('meetings') or []:
            url = m.get('agendaUrl') or m.get('minutesUrl')
            if not url:
                continue
            out.append(('%s — %s %s' % (place, m.get('title', ''), m.get('date', '')), url))
            n += 1
            if n >= per_place:
                break
    return out


def run(url):
    r = get_text(url)
    if r is None:
        return None, None, None, None
    text, method = r
    return classify(text), len(text), method, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--control', type=int, default=2,
                    help='control meetings sampled per place (default 2)')
    ap.add_argument('--slugs', default='',
                    help='comma-separated place slugs for the control set '
                         '(default: a couple from every place)')
    args = ap.parse_args()
    slugs = [s.strip() for s in args.slugs.split(',') if s.strip()]

    if not has_ocr():
        print('note: tesseract/pdftoppm not found — image-only PDFs will not '
              'classify (text-layer PDFs still work via pdftotext).\n')

    print('=== RECALL — known ALPR docs (every one should match) ===')
    recall_hit = 0
    for name, url in KNOWN_ALPR:
        hits, chars, method, text = run(url)
        if hits is None:
            print('  [FETCH-FAIL] %s' % name)
            continue
        ok = 'MATCH  ' if hits else 'MISS ! '
        recall_hit += 1 if hits else 0
        print('  %s chars=%-6s %-9s %s' % (ok, chars, method, name))
        if hits:
            print('           %s' % json.dumps(hits))
        # Always show the raw language near hint words — reveals the real
        # vocabulary behind a match, and why a MISS missed.
        for line in hint_context(text):
            print('           · %s' % line)

    print('\n=== FALSE POSITIVES — control meetings (most should be clean) ===')
    controls = control_docs(slugs, args.control)
    fp = 0
    scanned = 0
    for name, url in controls:
        hits, chars, method, text = run(url)
        if hits is None:
            print('  [FETCH-FAIL] %s' % name)
            continue
        scanned += 1
        if hits:
            fp += 1
            print('  HIT   chars=%-6s %s' % (chars, name))
            print('           %s' % json.dumps(hits))
            for line in hint_context(text):
                print('           · %s' % line)
    print('  (%d control docs clean of %d scanned)' % (scanned - fp, scanned))

    print('\n=== SUMMARY ===')
    print('  recall:          %d/%d known ALPR docs matched' % (recall_hit, len(KNOWN_ALPR)))
    print('  control hits:    %d/%d scanned (inspect each above — some may be '
          'real ALPR items, not false positives)' % (fp, scanned))


if __name__ == '__main__':
    main()
