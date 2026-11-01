#!/usr/bin/env python3
"""Invariants of the nimbleCMS calendar adapter (lib/nimblecal.py). No network.

Pinned, because each was a real feature of Thomas County's feed:
  * the agenda is the PDF button inside the event; a shared `Pending.pdf` placeholder
    (every unposted future meeting) is never published as an agenda;
  * an event with no real PDF is skipped, a filtered calendar is dropped;
  * minutes come from a separate listing and merge onto the board's meeting of the
    SAME DATE; committees never receive any; a minutes date with no calendar event
    stands alone; nothing before `from_year` survives from either source;
  * a year the feed cannot return fails the whole run rather than leaving a hole.

Run: python scripts/test_nimblecal.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import nimblecal as N  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


BASE = 'https://c.example/'


def ev(start, cal, title, pdf=None, label='Tentative Agenda'):
    html = '<p>Members</p>'
    if pdf:
        html += '<p><a class=\\"btn\\" href=\\"%s\\" target=\\"_blank\\">%s</a></p>' % (pdf, label)
    return {'start': start + 'T09:00:00-0400', 'calendar_name': cal, 'title': title,
            'full_details': html.replace('\\"', '"').replace('\/', '/')}


EVENTS = [
    ev('2026-10-13', 'County Commission', "Commissioners' Board Meeting", '/uploads/files/aa/bb/real.pdf'),
    ev('2026-11-10', 'County Commission', "Commissioners' Board Meeting", '/uploads/Documents/Agenda/Pending.pdf'),
    ev('2026-10-14', 'Public Works Committee', 'Public Works Committee', '/uploads/files/cc/dd/pw.pdf'),
    ev('2026-10-15', 'Other', 'Office closed', '/uploads/files/ee/ff/x.pdf'),
    ev('2026-10-16', 'Finance Committee', 'Finance Committee'),
    ev('2026-10-13', 'County Commission', 'Special Called Meeting', '/uploads/files/gg/hh/special.pdf'),
    ev('2026-10-20', 'Public Works Committee', 'Packet only', '/uploads/files/ii/jj/pk.pdf', label='Bid packet'),
]
LABELS = {'County Commission': 'Board of Commissioners'}

print('Events')
ms, rep = N.parse_events(EVENTS, BASE, LABELS, exclude=['Other'])
by = {m['id']: m for m in ms}
check(len(ms) == 4 and rep['noAgenda'] == 2 and rep['filtered'] == 1,
      'real PDFs kept; placeholder and PDF-less events skipped; filtered calendar dropped: %r %r' % (len(ms), rep))
check(by['2026-10-13-board-of-commissioners']['agendaUrl'] == BASE + 'uploads/files/aa/bb/real.pdf',
      'the agenda button resolves against the site')
check('2026-10-13-board-of-commissioners-2' in by, 'two board events on one date stay two meetings')
check(by['2026-10-20-public-works-committee']['agendaUrl'].endswith('pk.pdf'),
      'a lone PDF with no agenda label is still the best available')
check(all(m['minutesUrl'] is None for m in ms), 'no minutes from the calendar')
check([m['date'] for m in ms] == sorted((m['date'] for m in ms), reverse=True), 'newest first')

print('Minutes merge')
minutes = [
    {'date': '2026-10-13', 'minutesUrl': 'https://c.example/m/10132026.pdf', 'title': 'Board of Commissioners 2026-10-13'},
    {'date': '2026-09-08', 'minutesUrl': 'https://c.example/m/09082026.pdf', 'title': 'Board of Commissioners 2026-09-08'},
]
merged = N.merge_minutes(list(ms), minutes, 'Board of Commissioners')
mb = {m['id']: m for m in merged}
check(mb['2026-10-13-board-of-commissioners']['minutesUrl'].endswith('10132026.pdf'),
      'minutes attach to the board meeting of the same date')
check(mb['2026-10-14-public-works-committee']['minutesUrl'] is None, 'committees never receive minutes')
alone = mb['2026-09-08-board-of-commissioners']
check(alone['agendaUrl'] is None and alone['minutesUrl'].endswith('09082026.pdf'),
      'a minutes date with no calendar event stands alone')

print('Fetch wrapper')
calls = []


def fetcher(url):
    calls.append(url)
    return EVENTS if '2026-01-01' in url else []


got, bodies = N.fetch_nimblecal_meetings(
    'https://c.example/events', base_url=BASE, from_year=2026, body_labels=LABELS,
    minutes_url='https://c.example/files', fetcher=fetcher,
    minutes_fetcher=lambda u, b: ([dict(m, body=b) for m in minutes + [
        {'date': '2019-01-08', 'minutesUrl': 'https://c.example/m/old.pdf', 'title': 'old'}]], [b]))
check(got is not None and not any(m['date'].startswith('2019') for m in got),
      'nothing before from_year survives from the minutes listing')
check(calls[0].startswith('https://c.example/events/?start=2026-01-01'), 'history starts at from_year')
check('Board of Commissioners' in bodies and 'Public Works Committee' in bodies, 'bodies seen')
check(N.fetch_nimblecal_meetings('https://c.example/events', fetcher=lambda u: None) == (None, None),
      'a year that cannot be read fails the whole run')
check(N.fetch_nimblecal_meetings('https://c.example/events', fetcher=lambda u: [],
                                 ) == (None, None), 'a feed with no agendas at all is refused')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll nimbleCMS calendar invariants hold.')
