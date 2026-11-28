#!/usr/bin/env python3
"""`domains.meetings.topics_from: minutes` in enrich_ocr_meetings.py. No network.

The enricher reads a meeting's agenda first. Where the agenda link is a web page rather
than a document (Ben Hill: a WordPress post), that reads no text at all and the minutes
PDF sitting beside it is never opened. The setting makes a place read minutes only.

Pinned:
  * With the setting, the minutes PDF is what is fetched, and the record links to it.
  * A meeting with no minutes yet is left out, not recorded as unreadable.
  * Without the setting, the agenda is still read first.
  * A misspelt value fails the place instead of silently reading agendas.

Run: python scripts/test_enrich_minutes_only.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrich_ocr_meetings as E  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


HELD = {'id': '2026-10-06-regular', 'date': '2026-10-06', 'body': 'Board of Commissioners',
        'title': 'October 6, 2026 Regular Meeting',
        'agendaUrl': 'https://bh.example/oct-6/', 'minutesUrl': 'https://bh.example/oct.pdf'}
UPCOMING = {'id': '2026-11-03-regular', 'date': '2026-11-03', 'body': 'Board of Commissioners',
            'title': 'November 3, 2026 Regular Meeting',
            'agendaUrl': 'https://bh.example/nov-3/', 'minutesUrl': None}

fetched, written = [], []


def fake_fetch(url, **_):
    fetched.append(url)
    return b'%PDF-1.4 stand-in'


E.fetch_bytes = fake_fetch
E.extract_text = lambda path: ('The board heard a rezoning request.', 'pdftotext')
E.load_meetings = lambda slug: {'meetings': [dict(UPCOMING), dict(HELD)]}
E.load_cache = lambda slug: {}
E.write_json_atomic = lambda path, data, **_: written.append(data)


def run(cfg):
    del fetched[:], written[:]
    return E.enrich_place({'slug': 't', 'name': 'T County'}, cfg, '2026-01-01', 25)


print('topics_from: minutes')
run({'platform': 'htmltable', 'topics_from': 'minutes'})
check(fetched == [HELD['minutesUrl']], 'only the minutes PDF is fetched: %r' % fetched)
recs = written[0]['meetings'] if written else []
check([r['id'] for r in recs] == [HELD['id']],
      'a meeting with no minutes yet is left out: %r' % [r['id'] for r in recs])
check(bool(recs) and recs[0]['textSource'] == 'minutes'
      and recs[0]['sourceUrl'] == HELD['minutesUrl'], 'the record links to the minutes')

print('Default')
run({'platform': 'htmltable'})
check(fetched == [UPCOMING['agendaUrl'], HELD['agendaUrl']],
      'agendas are still read first: %r' % fetched)

print('Bad value')
try:
    run({'platform': 'htmltable', 'topics_from': 'minute'})
    refused = False
except ValueError as e:
    refused = 'topics_from' in str(e)
check(refused and not fetched, 'a misspelt value raises before anything is fetched')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nMinutes-only tagging holds.')
