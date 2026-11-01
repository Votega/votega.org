#!/usr/bin/env python3
"""Invariants of the Drupal meetings-view adapter (lib/drupalviews.py). No network.

Pinned, and why:
  * Columns are read by HEADER text, so a reordered or extra column still parses.
  * Two rows with the same date AND time are one meeting listed twice (Palmetto does
    this) and are merged, links unioned.
  * Saved-page mode keeps earlier records the page no longer shows; the live path
    does not (it rebuilds from the source).
  * A challenge page / markup change returns (None, None) rather than an empty list.
  * Bodies come from the detail URL's first path segment; an unmapped one falls back
    to the default and is reported, never dropped.

Run: python scripts/test_drupalviews.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import drupalviews as D  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


U = 'https://city.example/meetings'


def cell(label, inner):
    return '<td><strong class="tablesaw-cell-label" aria-hidden="true">%s</strong><span>%s</span></td>' % (label, inner)


def row(date, title, agenda=None, packet=None, detail=None, video=None):
    a = '<a href="%s"><img></a>' % agenda if agenda else ''
    p = '<a href="%s"><img></a>' % packet if packet else ''
    v = '<a href="%s">View Details</a>' % detail if detail else ''
    vid = '<a href="%s">v</a>' % video if video else ''
    return '<tr>%s%s%s%s%s%s</tr>' % (cell('Date', date), cell('Meeting', title), cell('Agendas', a),
                                      cell('Agenda Packets', p), cell('Video / Audio', vid), cell('View', v))


HEAD = '<thead><tr><th>Date</th><th>Meeting</th><th>Agendas</th><th>Agenda Packets</th><th>Video / Audio</th><th>View</th></tr></thead>'
PAGE = ('<table>' + HEAD + '<tbody>'
        + row('Nov 4, 2026 | 5:30pm', 'Work Session', '/media/1', None, '/citycouncil/meeting/work-session-49')
        + row('Nov 4, 2026 | 5:30pm', 'City Council Work Session Meeting, November 4, 2026 5:30 pm',
              None, '/media/2', '/citycouncil/meeting/city-council-work-session-nov-4')
        + row('Nov 4, 2026 | 7pm', 'Regular Meeting', '/media/3', '/media/4', '/citycouncil/meeting/regular-9')
        + row('Dec 1, 2026 | 5pm', 'Zoning Hearing', None, None, '/zba/meeting/hearing-1')
        + row('Mar 3, 2025 | 7pm', 'Council Meeting', None, None, '/citycouncil/meeting/old-1', video='/media/9')
        + row('Mar 4, 2025 | 7pm', 'Empty Past Row', None, None, '/citycouncil/meeting/old-2')
        + '</tbody></table>')

print('Parsing')
check(D.parse_date('Nov 4, 2026 | 5pm') == ('2026-11-04', '5pm'), 'date and time')
check(D.parse_date('Nov 4, 2026') == ('2026-11-04', None), 'a date with no time')
check(D.parse_date('TBD') == (None, None), 'no date -> None')
rows = D.parse_rows(PAGE, U)
check(len(rows) == 6 and rows[0]['agenda'] == ['https://city.example/media/1'],
      'rows parsed, links made absolute')
reordered = PAGE.replace('<th>Agendas</th><th>Agenda Packets</th>', '<th>Agenda Packets</th><th>Agendas</th>')
reordered = reordered.replace(cell('Agendas', '<a href="/media/1"><img></a>') + cell('Agenda Packets', ''),
                              cell('Agenda Packets', '') + cell('Agendas', '<a href="/media/1"><img></a>'))
check(D.parse_rows(reordered, U)[0]['agenda'] == ['https://city.example/media/1'],
      'a reordered column is still read by its header')

print('Meetings')
ms, bodies = D.fetch_drupalviews_meetings(U, body_paths={'citycouncil': 'City Council', 'zba': 'Zoning Board'},
                                          pages=[(U, PAGE)], today='2026-11-01')
by = {m['date'] + m['body']: m for m in ms}
check(len(ms) == 4, 'two rows for one 5:30 work session merge into one meeting (empty past row dropped)')
ws = [m for m in ms if m['date'] == '2026-11-04' and 'Work Session' in m['title']][0]
check(ws['agendaUrl'].endswith('/media/1') and ws['agendaPacketUrl'].endswith('/media/2'),
      'the merged meeting carries both rows\' links')
check('November 4, 2026' in ws['title'], 'the longer title is kept')
reg = [m for m in ms if m['title'] == 'Regular Meeting'][0]
check(reg['agendaPacketUrl'].endswith('/media/4') and reg['minutesUrl'] is None, 'packet link kept; no minutes column -> None')
check(bodies == ['City Council', 'Zoning Board'], 'bodies from the detail URL path: %s' % bodies)
zb = [m for m in ms if m['body'] == 'Zoning Board'][0]
check(zb['agendaUrl'] is None, 'a FUTURE meeting with no files yet is kept')
old = [m for m in ms if m['title'] == 'Council Meeting'][0]
check(old['videoUrl'].endswith('/media/9'), 'the Video / Audio column fills videoUrl')
check(not any(m['title'] == 'Empty Past Row' for m in ms), 'a PAST meeting with nothing to open is dropped')
ms2, bodies2 = D.fetch_drupalviews_meetings(U, body_paths={'citycouncil': 'City Council'}, pages=[(U, PAGE)], today='2026-11-01')
check('City Council' in bodies2 and len(ms2) == 4, 'an unmapped body path falls back to the default')

print('Saved pages vs live')
prev = [{'id': '2026-10-06-regular-8', 'date': '2026-10-06', 'body': 'City Council', 'title': 'Regular', 'agendaUrl': 'https://x/a.pdf'}]
saved, _ = D.fetch_drupalviews_meetings(U, pages=[(U, PAGE)], previous=prev, today='2026-11-01')
check(any(m['id'] == '2026-10-06-regular-8' for m in saved), 'saved pages keep earlier records')
live, _ = D.fetch_drupalviews_meetings(U, previous=prev, fetcher=lambda u: PAGE.encode(), today='2026-11-01')
check(not any(m['id'] == '2026-10-06-regular-8' for m in live), 'a live read rebuilds from the source')
check(D.fetch_drupalviews_meetings(U, fetcher=lambda u: None) == (None, None), 'unreadable page -> (None, None)')
check(D.fetch_drupalviews_meetings(U, fetcher=lambda u: b'<html>Just a moment...</html>') == (None, None),
      'a challenge page with no table -> (None, None)')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll Drupal-view invariants hold.')
