#!/usr/bin/env python3
"""Invariants of the HTML table adapter (lib/htmltable.py). No network.

The fixture is a trimmed copy of Houston County's real Meeting Minutes page: the 8
newest rows plus the older rows that exercise folding and same-day meetings.

What is pinned, and why:
  * The Oct 20, 2026 agenda / minutes / video are checked against links a person
    supplied by hand - an independent source of truth.
  * Houston prints a hidden YYYYMMDD directly before the visible date (the cell reads
    `202609229/22/2026`); the date must come out right, not `29/22/2026`.
  * File names with spaces and double spaces are percent-encoded once, not twice.
  * An agenda-only row (Nov 3) keeps minutesUrl and videoUrl as None, not "".
  * Columns are found by header text, so a reordered table lands the same documents.
  * A layout change fails loudly instead of publishing meetings without links.

Run: python scripts/test_htmltable.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import htmltable as H  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(HERE, 'fixtures', 'htmltable-houston.html'), encoding='utf-8').read()
BASE = 'https://www.houstoncountyga.gov/commissioner/meeting-minutes.cms'
FILES = 'https://www.houstoncountyga.gov/minutes/'

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


meetings, rep = H.parse_table(HTML, BASE, body='Board of Commissioners')
by_id = {m['id']: m for m in meetings}

print('Real page fixture')
check(rep['skippedRows'] == [], 'no row skipped: %r' % rep['skippedRows'])
check([m['date'] for m in meetings] == sorted((m['date'] for m in meetings), reverse=True),
      'newest first')
oct20 = by_id['2026-10-20-meeting']
check(oct20['agendaUrl'] == FILES + '2026-10-20%20Department%20Head%20Copy.pdf',
      'Oct 20 agenda is the document the county gave us')
check(oct20['minutesUrl'] == FILES + '2026-10-20%20%20Minutes.pdf',
      'Oct 20 minutes is the document the county gave us (double space encoded once)')
check(oct20['videoUrl'] == 'https://vimeo.com/1233404332', 'Oct 20 video link')
check(oct20['title'] == 'October 20, 2026 Meeting', 'title: %r' % oct20['title'])
nov3 = by_id['2026-11-03-meeting']
check(nov3['agendaUrl'] and nov3['minutesUrl'] is None and nov3['videoUrl'] is None,
      'an agenda-only row leaves minutes and video None (not "")')
check(all('%2520' not in (u or '') for m in meetings
          for u in (m['agendaUrl'], m['minutesUrl'])), 'nothing is double-encoded')
check(set(m['body'] for m in meetings) == {'Board of Commissioners'}, 'body label applied')

print('Dates')
check(H._row_date({'text': '202609229/22/2026', 'links': [('/x', '9/22/2026')]}) == '2026-09-22',
      'hidden YYYYMMDD glued to the visible date is read correctly')
check(H._row_date({'text': '20260922 9/22/2026', 'links': []}) == '2026-09-22', 'with a space too')
check(H._row_date({'text': '202609229/23/2026', 'links': [('/x', '9/23/2026')]}) is None,
      'hidden and visible dates that disagree -> skipped, not guessed')
check(H._row_date({'text': '13/45/2026', 'links': []}) is None, 'impossible date -> None')

print('Same-date rows')
check(by_id['2015-09-15-meeting']['agendaUrl'] and by_id['2015-09-15-meeting']['minutesUrl'],
      'an agenda row and a minutes row for one date fold into one meeting')
aug19 = [m for m in meetings if m['date'] == '2025-08-19']
check(len(aug19) >= 1 and len({m['id'] for m in aug19}) == len(aug19),
      'same-day meetings keep distinct ids (%d)' % len(aug19))

print('Columns come from header text')
swapped = HTML.replace('<th>Agenda</th>', '<th>TMP</th>').replace('<th>Minutes</th>', '<th>Agenda</th>') \
              .replace('<th>TMP</th>', '<th>Minutes</th>')
sw = {m['id']: m for m in H.parse_table(swapped, BASE)[0]}
check(sw['2026-10-20-meeting']['agendaUrl'] == oct20['minutesUrl'],
      'swapping the headers swaps which documents are agendas (never position)')

print('Failure modes')
check(raises(lambda: H.parse_table('<html><body><p>nothing</p></body></html>', BASE),
             'no meetings table'), 'no table -> refuse')
no_links = re.sub(r'<a href="/(minutes|skins)[^>]*>[^<]*</a>', '', HTML)
no_links = re.sub(r'<a href="https://vimeo[^>]*>.*?</a>', '', no_links, flags=re.S)
check(raises(lambda: H.parse_table(no_links, BASE), 'layout has changed'),
      'rows but no document links -> refuse (layout change)')
check(raises(lambda: H.parse_table(HTML.replace('<th>Date</th>', '<th>When</th>'), BASE),
             'no meetings table'), 'unrecognised date header -> refuse')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll HTML table adapter invariants hold.')
