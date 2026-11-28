#!/usr/bin/env python3
"""`domains.meetings.drop_empty_headings` - template lines that say nothing happened.

Ben Hill's minutes print every standing heading even when there is no business under it
("Rezoning Application: NONE"), so nearly every meeting was tagged land use for
rezonings and annexations that never happened. No network.

Pinned (the lines are copied from the county's 2026 minutes):
  * A whole line "<heading>: NONE" or "<heading>: No Action Required" is removed.
  * A heading with business under it, or on its line, is kept.
  * "NONE" inside a sentence is left alone.
  * The enricher applies it only to a place that opts in, and still caches the RAW text,
    marked so the lexicon scorer can reproduce what production classified.

Run: python scripts/test_empty_headings.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrich_ocr_meetings as E  # noqa: E402
from lib.meeting_topics import classify, drop_empty_headings  # noqa: E402
from lib.text_cache import open_cache  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


EMPTY = ('Roads are passable.\r\n'
         '  Annexation Request/Notification: NONE\r\n'
         'Annexation Notification: No Action Required\r\n'
         'Rezoning Application: NONE\n'
         'Alcohol Application: NONE\n'
         'Appointments: NONE\n'
         'Old Business: NONE\n'
         'Meeting adjourned.\n')
REAL = ('Rezoning Application:\n'
        'Rezoning 245 Pine Level Church Road from GL to WLI\n'
        'Annexation Request: 12 Oak Street\n'
        "Commissioner's Remarks: None of the rezoning signs were posted.\n")

print('The function')
out = drop_empty_headings(EMPTY)
check(out.split() == 'Roads are passable. Meeting adjourned.'.split(),
      'every empty standing line is removed: %r' % out)
check(classify(out) == [], 'so nothing is tagged from them: %r' % classify(out))
check(drop_empty_headings(REAL) == REAL,
      'a heading with business, and "None" inside a sentence, are untouched')
check(drop_empty_headings('') == '' and drop_empty_headings(None) is None, 'empty input')

print('The enricher')
written = []
E.fetch_bytes = lambda url, **_: b'%PDF-1.4 stand-in'
E.extract_text = lambda path: (EMPTY, 'pdftotext')
E.load_meetings = lambda slug: {'meetings': [
    {'id': 'm', 'date': '2026-06-02', 'body': 'Board', 'title': 'June 2 Meeting',
     'agendaUrl': None, 'minutesUrl': 'https://bh.example/june.pdf'}]}
E.load_cache = lambda slug: {}
E.write_json_atomic = lambda path, data, **_: written.append(data)
root = tempfile.mkdtemp()
try:
    cache = open_cache(root, writable=True)
    E.enrich_place({'slug': 't', 'name': 'T'}, {'platform': 'htmltable',
                   'drop_empty_headings': True}, '2026-01-01', 25, text_cache=cache)
    check(written[-1]['meetings'][0]['tags'] == [], 'an opted-in place gets no tags')
    # (The cache reads text back with universal newlines, so compare the lines.)
    check(cache.text_for('t', 'm').split() == EMPTY.split(), 'the cache keeps the raw text')
    check(cache.entry('t', 'm').get('emptyHeadingsDropped') is True,
          'and records that production drops the empty headings')
    E.enrich_place({'slug': 't', 'name': 'T'}, {'platform': 'htmltable',
                   'drop_empty_headings': True}, '2026-01-01', 25, reclassify=True,
                   text_cache=cache, from_text_cache=True)
    check(written[-1]['meetings'][0]['tags'] == [], 'an offline re-tag drops them too')
    E.enrich_place({'slug': 't', 'name': 'T'}, {'platform': 'htmltable'}, '2026-01-01', 25)
    check('rezoning' in written[-1]['meetings'][0]['tags'], 'other places are unchanged')
finally:
    shutil.rmtree(root, ignore_errors=True)

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nEmpty-heading handling holds.')
