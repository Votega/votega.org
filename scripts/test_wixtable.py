#!/usr/bin/env python3
"""Invariants of the Wix table adapter (lib/wixtable.py). No network, no browser.

The fixture is a geometry snapshot of Baker County's real Minutes and Agendas page
(23 rendered rows, 44 icons), captured through the adapter's own COLLECT_JS.

What is pinned, and why:
  * Documents land in the row/column they visually sit in. The Sept 11, 2026 pair is
    checked against links a person supplied by hand - an independent source of truth.
  * A row whose date is malformed (the county typed "July 16, 206") is skipped, never
    repaired, and is reported.
  * Two meetings on one date stay two records (July 7 has a Called and a Regular).
  * A layout change fails loudly instead of publishing meetings stripped of links.
  * A cell holding two different documents gets neither.

Run: python scripts/test_wixtable.py
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import wixtable as W  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = json.load(open(os.path.join(HERE, 'fixtures', 'wixtable-baker-snapshot.json'),
                      encoding='utf-8'))
UGD = 'https://www.bakercountyga.com/_files/ugd/551ef8_'

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def raises(fn, needle):
    try:
        fn()
    except ValueError as e:
        return needle in str(e)
    return False


meetings, rep = W.parse_snapshot(copy.deepcopy(SNAP))
by_id = {m['id']: m for m in meetings}

print('Real page snapshot')
check(len(meetings) == 22, '22 meetings from 23 rows (got %d)' % len(meetings))
check(rep['skippedRows'] == ['July 16, 206 | Public Hearing'],
      'the malformed-date row is skipped and reported: %r' % rep['skippedRows'])
check(rep['orphans'] == 0, 'every in-table icon landed in a cell')
check(rep['documents'] == 42, '42 documents linked (got %d)' % rep['documents'])
check([m['date'] for m in meetings] == sorted((m['date'] for m in meetings), reverse=True),
      'newest first')

print('Row / column assignment')
sep = by_id['2026-09-11-called-meeting']
check(sep['agendaUrl'] == UGD + '12ae5b319bd74cc2967a285e439fc432.pdf',
      'Sept 11 agenda is the document the county gave us')
check(sep['minutesUrl'] == UGD + 'e6407ba066a14b7abe0c1db7e454e06d.pdf',
      'Sept 11 minutes is the document the county gave us')
check('2026-07-07-called-meeting' in by_id and '2026-07-07-regular-meeting' in by_id,
      'two meetings on July 7 stay two records')
check(by_id['2026-07-07-called-meeting']['agendaUrl'] != by_id['2026-07-07-regular-meeting']['agendaUrl'],
      '...each with its own agenda')
check(by_id['2026-10-28-called-meeting']['minutesUrl'] is None
      and by_id['2026-10-28-called-meeting']['agendaUrl'],
      'an agenda with no minutes yet leaves minutesUrl null (not an empty string)')
check(all(not m['agendaUrl'] or '/_files/ugd/' in m['agendaUrl'] for m in meetings),
      'only meeting documents are linked, never the tax notices above the table')
check(by_id['2026-07-23-data-center-info-meeting']['title'] == 'July 23, 2026 Data Center Info Meeting',
      'title reads naturally: %r' % by_id['2026-07-23-data-center-info-meeting']['title'])
check(set(m['body'] for m in meetings) == {'Board of Commissioners'}, 'body label applied')

print('Dates')
check(W.parse_date('January  6, 2026') == '2026-01-06', 'double space and no zero pad')
check(W.parse_date('July 16, 206') is None, 'three-digit year is not repaired')
check(W.parse_date('Sept 11, 2026') is None, '"Sept" is not guessed')
check(W.parse_date('') is None and W.parse_date(None) is None, 'empty is None')

print('Failure modes')
no_icons = copy.deepcopy(SNAP)
no_icons['icons'] = [i for i in no_icons['icons'] if i['y'] < no_icons['table']['top']]
check(raises(lambda: W.parse_snapshot(no_icons), 'layout has changed'),
      'rows but no document in any cell -> refuse (layout change)')

shifted = copy.deepcopy(SNAP)
for i in shifted['icons']:
    i['x'] += 500          # every icon now off to the right of every column
check(raises(lambda: W.parse_snapshot(shifted), 'layout has changed'),
      'icons landing in no cell -> refuse')

bad_headers = copy.deepcopy(SNAP)
bad_headers['columns'][2]['label'] = 'Packet'
check(raises(lambda: W.parse_snapshot(bad_headers), 'headers not recognised'),
      'unrecognised headers -> refuse')

check(raises(lambda: W.parse_snapshot(None), 'no table rows')
      and raises(lambda: W.parse_snapshot({'rows': []}), 'no table rows'),
      'no table -> refuse')

dup = copy.deepcopy(SNAP)
row = next(r for r in dup['rows'] if 'September 11' in r['cells'][0])
ag = dup['columns'][2]
dup['icons'].append({'href': UGD + 'deadbeef.pdf', 'x': (ag['left'] + ag['right']) / 2,
                     'y': (row['top'] + row['bottom']) / 2, 'w': 28, 'h': 31})
m2, rep2 = W.parse_snapshot(dup)
s2 = next(m for m in m2 if m['id'] == '2026-09-11-called-meeting')
check(s2['agendaUrl'] is None and ('2026-09-11', 'agenda') in rep2['ambiguousCells'],
      'two different documents in one cell -> neither is linked, and it is reported')
check(s2['minutesUrl'] == UGD + 'e6407ba066a14b7abe0c1db7e454e06d.pdf',
      '...while the same row\'s other cell is unaffected')

print('Fetch wrapper')
calls = []


def flaky(url, timeout=0):
    calls.append(url)
    if len(calls) == 1:
        raise RuntimeError('browser hiccup')
    return copy.deepcopy(SNAP)


got, bodies = W.fetch_wixtable_meetings('https://x/y', snapshotter=flaky)
check(got is not None and len(got) == 22 and bodies == ['Board of Commissioners'] and len(calls) == 2,
      'one retry rescues a transient browser failure')
got, bodies = W.fetch_wixtable_meetings('https://x/y', snapshotter=lambda u, timeout=0: None)
check(got is None and bodies is None, 'a page that cannot be read returns (None, None)')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll Wix table adapter invariants hold.')
