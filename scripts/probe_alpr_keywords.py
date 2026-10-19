#!/usr/bin/env python3
"""Measure the SHIPPED `alpr` keyword lexicon against real agenda/minutes PDFs.

A DIAGNOSTIC, not part of the build. The `alpr` subject rule has shipped in
lib/meeting_topics.py; this script answers the standing question about it: does
the lexicon actually catch license-plate-reader / surveillance discussions in
the wild (recall), and how often does it fire on meetings that have nothing to do
with ALPR (false positives)?

It owns corpora and hint words, NEVER keywords. The matcher is
lib.meeting_topics.classify() / matched_terms() — the exact code the enrichers
run, including its split between plain-substring phrases and whole-word acronyms
— so the numbers here describe the matcher that ships. (An earlier version kept a
private copy of the candidate lexicon and word-bounded every term; it drifted
from production in both coverage and matching semantics and so measured a
matcher that did not exist. test_meeting_topics_alpr.py now guards against that
duplication returning.) To change what matches, edit lib/meeting_topics.py and
add a case to test_meeting_topics_alpr.py, then re-run this probe to see the
effect on real documents.

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
              terms fired so you can judge).

Hits are reported as evidence terms split into VENDOR (named brands, shown by
display name) and GENERIC (capability language such as "plate reader", plus the
bare agenda spelling "flock" which is vendor-labelled but also the plain word).
A vendor-attributed hit is a different kind of finding from a generic-only one.

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
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from lib.http import fetch_bytes  # noqa: E402
from lib.meeting_topics import (ALPR_TERMS, ALPR_VENDOR_LABELS,  # noqa: E402
                                alpr_vendors, classify, matched_terms)
from lib.pdf_text import extract_text, has_ocr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'assets', 'data')

_PDF_HEADERS = {
    'User-Agent': 'votega.org/1.0 (alpr-keyword-probe)',
    'Accept':     'application/pdf',
}

# ── Diagnostic-only vocabulary ─────────────────────────────────────────────────
# History worth keeping (the lexicon itself now lives in lib/meeting_topics.py):
# the first real run (recall 1/3) proved a generic capability net alone under-
# matches — agenda/minutes language calls the company plain "Flock" and its
# product "cameras", not "license plate reader" — so bare `flock` is REQUIRED for
# recall. It carries a false-positive risk ("a flock of geese"), which is why it
# is whole-word there (\bflock\b skips "flocking"/"flocked") and why this probe
# prints context around every hint word, so real FPs are caught by eye. Ambiguous
# tokens such as a lone vendor surname ('leonardo') and the bare parent brand
# 'motorola solutions' were rejected for over-matching non-ALPR contracts.
#
# HINT_WORDS deliberately stays LOCAL and must NOT be derived from the lexicon.
# Its whole job is to surface vocabulary that is NOT yet a keyword, so a missed
# known-ALPR doc reveals the raw language to consider adding. Deriving it from
# ALPR_TERMS would make it blind to exactly what it exists to find. Not used to
# tag anything.
HINT_WORDS = ['flock', 'license plate', 'plate reader', 'lpr', 'alpr', 'camera',
              'surveillance', 'safer city', 'safe city', 'real-time crime',
              'security camera', 'genetec', 'rekor', 'motorola', 'vigilant']


def classify_alpr(text):
    """Return the ALPR evidence for `text` using the production matcher.

    A doc is a hit iff the shipped classifier tags it `alpr`; the evidence is the
    matched keywords that belong to the ALPR lexicon (matched_terms also reports
    keywords for other subjects, which are not ALPR evidence). Returns None for a
    miss, else {'terms': [...], 'vendors': [display names], 'generic': [...]}.
    """
    if 'alpr' not in classify(text):
        return None
    terms = sorted(set(matched_terms(text)) & ALPR_TERMS)
    return {
        'terms': terms,
        'vendors': alpr_vendors(terms),
        'generic': [t for t in terms if t not in ALPR_VENDOR_LABELS],
    }


def fmt_hit(hit):
    """One CI-log line: vendor-attributed vs generic-capability evidence."""
    return 'vendors=%s  generic=%s' % (
        ', '.join(hit['vendors']) or '-', ', '.join(hit['generic']) or '-')


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
    """Returns None on a fetch failure (NOT a keyword result); otherwise
    (hit, chars, method, text) where hit is None for a clean miss."""
    r = get_text(url)
    if r is None:
        return None
    text, method = r
    return classify_alpr(text), len(text), method, text


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
        res = run(url)
        if res is None:
            print('  [FETCH-FAIL] %s' % name)
            continue
        hits, chars, method, text = res
        ok = 'MATCH  ' if hits else 'MISS ! '
        recall_hit += 1 if hits else 0
        print('  %s chars=%-6s %-9s %s' % (ok, chars, method, name))
        if hits:
            print('           %s' % fmt_hit(hits))
        # Always show the raw language near hint words — reveals the real
        # vocabulary behind a match, and why a MISS missed.
        for line in hint_context(text):
            print('           · %s' % line)

    print('\n=== FALSE POSITIVES — control meetings (most should be clean) ===')
    controls = control_docs(slugs, args.control)
    fp = 0
    scanned = 0
    for name, url in controls:
        res = run(url)
        if res is None:
            print('  [FETCH-FAIL] %s' % name)
            continue
        hits, chars, method, text = res
        scanned += 1
        if hits:
            fp += 1
            print('  HIT   chars=%-6s %s' % (chars, name))
            print('           %s' % fmt_hit(hits))
            for line in hint_context(text):
                print('           · %s' % line)
    print('  (%d control docs clean of %d scanned)' % (scanned - fp, scanned))

    print('\n=== SUMMARY ===')
    print('  recall:          %d/%d known ALPR docs matched' % (recall_hit, len(KNOWN_ALPR)))
    print('  control hits:    %d/%d scanned (inspect each above — some may be '
          'real ALPR items, not false positives)' % (fp, scanned))


if __name__ == '__main__':
    main()
