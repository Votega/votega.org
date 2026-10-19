#!/usr/bin/env python3
"""The enrichers' --from-text-cache path, for both PDF and Granicus places.

This path exists so a taxonomy change can re-tag the whole history from the local
text corpus instead of re-downloading ~800 documents. It is the path that runs
LEAST often and touches the most committed data, which is a bad combination: the
first real use of it crashed on the Granicus side with

    UnboundLocalError: cannot access local variable 'raw'

because the record builder still hashed the fetched bytes (`contentSha256`) on a
path where nothing is ever fetched. The place-level guard contained it — four
places kept their existing data rather than publishing a short window — so no bad
data shipped, but a whole run was wasted. These tests pin the properties that bug
violated:

  * a from-cache run FETCHES NOTHING (any network call here is the bug the flag
    exists to prevent, and a silent fallback would make an "offline" run cost 800
    downloads);
  * it produces a COMPLETE record, with every field the fetching path fills —
    including the ones derived from bytes, which must be carried from the prior
    record rather than recomputed or dropped;
  * a cache MISS keeps the meeting's prior tags instead of wiping them;
  * the classification matches what the fetching path would have produced.

Run: python scripts/test_enrich_from_text_cache.py     (no network, no repo writes)
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.text_cache import open_cache  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def boom(*a, **k):                      # any network call is a failure
    raise AssertionError('from-cache run attempted a network fetch')


ALPR_TEXT = 'Approve agreement with Flock Safety for ALPR cameras at county entrances'

tmp = tempfile.mkdtemp(prefix='votega-fromcache-test-')
try:
    root = os.path.join(tmp, 'corpus')
    w = open_cache(root, writable=True)
    w.record('newton', '7', ALPR_TEXT, method='pdftotext', pdf_sha='pdfsha123',
             source_url='https://example.gov/a.pdf', date='2026-04-15', body='BOC')
    w.record('barrow', '9', ALPR_TEXT, method='html',
             source_url='https://example.gov/view.php', date='2026-05-01', body='BOC')
    w.flush()
    rd = open_cache(root)

    # ── PDF-platform enricher ────────────────────────────────────────────────
    import enrich_ocr_meetings as OCR
    OCR.fetch_bytes = boom
    OCR.extract_text = boom
    meeting = {'id': '7', 'date': '2026-04-15', 'body': 'BOC', 'title': 'Regular',
               'agendaUrl': 'https://example.gov/a.pdf'}
    prior = {'7': {'id': '7', 'tags': ['contract'], 'pdfSha256': 'oldsha',
                   'textSourceUrl': 'https://example.gov/a.pdf'}}
    rec = OCR.enrich_meeting(dict(meeting), prior, reclassify=True, slug='newton',
                             text_cache=rd, from_text_cache=True)
    check('ocr: classifies from cache without fetching', 'alpr' in rec['tags'], True)
    check('ocr: carries the cached extraction method', rec['textMethod'], 'pdftotext')
    check('ocr: pdfSha256 is present, not None',
          rec['pdfSha256'], 'pdfsha123')
    check('ocr: record is complete',
          sorted(k for k in ('id', 'date', 'tags', 'topics', 'matchedTerms', 'flags',
                             'textChars', 'textMethod', 'pdfSha256', 'sourceUrl')
                 if rec.get(k) in (None, '')), [])

    miss = dict(meeting); miss['id'] = '404'
    prior_miss = {'404': {'id': '404', 'tags': ['rezoning']}}
    rec2 = OCR.enrich_meeting(miss, prior_miss, reclassify=True, slug='newton',
                              text_cache=rd, from_text_cache=True)
    check('ocr: a cache miss keeps prior tags', rec2['tags'], ['rezoning'])

    # ── Granicus enricher ────────────────────────────────────────────────────
    # The regression: this path never fetches, so contentSha256 must come from the
    # prior record. Hashing the (nonexistent) response bytes raised UnboundLocalError.
    import enrich_granicus_meetings as GRAN
    GRAN.fetch_agenda_html = boom
    GRAN.extract_text = boom
    gmeeting = {'id': '9', 'date': '2026-05-01', 'body': 'BOC', 'title': 'Regular',
                'agendaUrl': 'https://example.gov/view.php'}
    gprior = {'9': {'id': '9', 'tags': ['contract'], 'contentSha256': 'htmlsha456',
                    'textSourceUrl': 'https://example.gov/view.php'}}
    grec = GRAN.enrich_meeting(dict(gmeeting), gprior, reclassify=True, slug='barrow',
                               text_cache=rd, from_text_cache=True)
    check('granicus: classifies from cache without fetching',
          'alpr' in grec['tags'], True)
    check('granicus: carries the cached extraction method', grec['textMethod'], 'html')
    check('granicus: contentSha256 carried from the prior record',
          grec['contentSha256'], 'htmlsha456')
    check('granicus: record is complete',
          sorted(k for k in ('id', 'date', 'tags', 'topics', 'matchedTerms', 'flags',
                             'textChars', 'textMethod', 'sourceUrl')
                 if grec.get(k) in (None, '')), [])

    # No prior record at all: the hash is simply absent, and the run still succeeds
    # rather than raising. A first-ever from-cache enrichment is a real scenario.
    grec2 = GRAN.enrich_meeting(dict(gmeeting), {}, reclassify=True, slug='barrow',
                                text_cache=rd, from_text_cache=True)
    check('granicus: no prior record still yields a usable record',
          'alpr' in grec2['tags'], True)
    check('granicus: absent prior hash is None, not a crash',
          grec2['contentSha256'], None)

    gmiss = dict(gmeeting); gmiss['id'] = '404'
    grec3 = GRAN.enrich_meeting(gmiss, {'404': {'id': '404', 'tags': ['variance']}},
                                reclassify=True, slug='barrow',
                                text_cache=rd, from_text_cache=True)
    check('granicus: a cache miss keeps prior tags', grec3['tags'], ['variance'])

    # Both enrichers must agree with each other on the same text.
    check('both enrichers classify the same text identically',
          sorted(rec['tags']) == sorted(grec['tags']), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All from-text-cache checks passed.')
