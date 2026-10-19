#!/usr/bin/env python3
"""Invariant checks for lib/text_cache.py — the offline meeting-text corpus.

The cache is what makes a lexicon change measurable (score_topic_lexicon.py) and
what lets `--reclassify --from-text-cache` re-tag history without re-downloading
~800 PDFs. Both uses are only as trustworthy as the cache's read path, so this
pins the properties they depend on:

  * content addressing — the key is the sha256 of the text, so it round-trips and
    de-duplicates;
  * a READER never writes (a scorer must not half-populate a corpus);
  * an unreadable document is SKIPPED by documents(), never yielded as empty text,
    because a scorer that scored empty text would bank a false clean negative;
  * manifest keys survive a save/reload for int meeting ids (Legistar).

Run: python scripts/test_text_cache.py       (no network, no repo writes)
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.text_cache import TextCache, open_cache, text_sha  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


tmp = tempfile.mkdtemp(prefix='votega-text-cache-test-')
try:
    root = os.path.join(tmp, 'cache')

    # ── write + round-trip ───────────────────────────────────────────────────
    w = open_cache(root, writable=True)
    sha = w.record('newton', '1006', 'Flock Safety ALPR cameras', method='pdftotext',
                   pdf_sha='deadbeef', source_url='https://example.gov/a.pdf',
                   date='2026-04-15', body='BOC')
    check('record returns the text sha', sha, text_sha('Flock Safety ALPR cameras'))
    check('text round-trips before flush', w.text_for('newton', '1006'),
          'Flock Safety ALPR cameras')
    check('flush persists a dirty manifest', w.flush(), True)
    check('second flush is a no-op', w.flush(), False)

    # Blob path is content-addressed with a two-char fan-out.
    blob = os.path.join(root, 'text', sha[:2], '%s.txt.gz' % sha)
    check('blob written at its fan-out path', os.path.exists(blob), True)

    # ── reload ───────────────────────────────────────────────────────────────
    r = open_cache(root)
    check('manifest reloads', r.text_for('newton', '1006'), 'Flock Safety ALPR cameras')
    check('entry carries the upstream pdf sha',
          (r.entry('newton', '1006') or {}).get('pdfSha256'), 'deadbeef')
    check('miss returns None', r.text_for('newton', 'nope'), None)

    # ── a reader must never write ────────────────────────────────────────────
    before = sorted(os.listdir(os.path.join(root, 'text')))
    r.record('newton', '2000', 'should not be stored')
    check('reader.record() stores nothing', r.text_for('newton', '2000'), None)
    check('reader.record() leaves the tree untouched',
          sorted(os.listdir(os.path.join(root, 'text'))), before)
    check('reader.flush() is a no-op', r.flush(), False)

    # ── int meeting ids survive a JSON round-trip (Legistar) ─────────────────
    w2 = open_cache(root, writable=True)
    w2.record('fulton', 12345, 'Automated license plate reader program')
    w2.flush()
    r2 = open_cache(root)
    check('int meeting id survives reload',
          r2.text_for('fulton', 12345), 'Automated license plate reader program')
    check('int and str ids address the same row',
          r2.text_for('fulton', '12345'), 'Automated license plate reader program')

    # ── de-duplication ───────────────────────────────────────────────────────
    w3 = open_cache(root, writable=True)
    n_before = len(os.listdir(os.path.join(root, 'text', sha[:2])))
    w3.record('cobb', '77', 'Flock Safety ALPR cameras')   # same text, other meeting
    w3.flush()
    check('identical text is stored once',
          len(os.listdir(os.path.join(root, 'text', sha[:2]))), n_before)
    check('both meetings read the shared blob',
          open_cache(root).text_for('cobb', '77'), 'Flock Safety ALPR cameras')

    # ── a missing blob is skipped, never scored as empty ─────────────────────
    # Three rows exist: newton/1006, fulton/12345 and cobb/77. newton/2000 was
    # offered to a READER and correctly never stored, which is asserted above.
    r3 = open_cache(root)
    keys_before = {k for k, _, _ in r3.documents()}
    check('every stored meeting is readable', sorted(keys_before),
          ['cobb/77', 'fulton/12345', 'newton/1006'])
    # newton/1006 and cobb/77 share one de-duplicated blob, so removing it takes
    # both rows out at once — exactly the risk content addressing introduces.
    os.remove(blob)
    r4 = open_cache(root)
    docs = {k for k, _, _ in r4.documents()}
    check('rows whose blob is gone are skipped', sorted(docs),
          ['fulton/12345'])
    check('stats reports the gap', r4.stats()['missing'], 2)
    check('stats still counts every entry', r4.stats()['entries'], 3)
    check('no document is yielded with empty text',
          [k for k, _, t in r4.documents() if not t], [])

    # ── open_cache(None) ─────────────────────────────────────────────────────
    check('open_cache(None) is None', open_cache(None), None)
    check('open_cache("") is None', open_cache(''), None)

    # ── a reader does not create the root ────────────────────────────────────
    ghost = os.path.join(tmp, 'absent')
    g = open_cache(ghost)
    check('reader on a missing root yields no documents', list(g.documents()), [])
    check('reader did not create the root', os.path.exists(ghost), False)

    # ── a corrupt member reads as a miss, not a crash ────────────────────────
    w4 = open_cache(root, writable=True)
    s4 = w4.record('henry', '9', 'gunfire detection and alert program')
    w4.flush()
    with open(os.path.join(root, 'text', s4[:2], '%s.txt.gz' % s4), 'wb') as fh:
        fh.write(b'not gzip at all')
    check('corrupt blob reads as a miss', open_cache(root).text_for('henry', '9'), None)

    # ── a truncated manifest does not take a run down ────────────────────────
    with open(os.path.join(root, 'manifest.json'), 'w', encoding='utf-8') as fh:
        fh.write('{"entries": {"newton/1006": ')      # truncated mid-object
    check('truncated manifest degrades to empty', list(open_cache(root).entries()), [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All text-cache checks passed.')
