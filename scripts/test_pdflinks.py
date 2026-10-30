#!/usr/bin/env python3
"""Invariants of the loose-PDF adapter (lib/pdflinks.py).

The fixtures are real file names and link texts from Appling, Atkinson and Bacon
counties (the three places it exists for), because the whole value of this adapter
is in the date spellings clerks actually use and the ones that must NOT be read.

Pinned here: every full-date spelling resolves; month+day with no year takes its
year from the /uploads/YYYY/MM/ path or, on a newest-first list, from the dated
link above it (December meetings filed in January roll back a year); the genuinely
ambiguous names (`Oct 25`, `09-26`, `122022`, `September 2025`, `Agenda-2`) are
SKIPPED rather than guessed; kind comes from the link text before the file name;
a "Combined" file listed twice fills both slots; http links on an https page are
upgraded and spaces encoded; a failed fetch is (None, None) even if another page
succeeded; and undated/keyword-less links never become meetings.

Run: python scripts/test_pdflinks.py       (no network, no repo writes)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import pdflinks
from lib.pdflinks import parse_date, parse_page, build_meetings, fetch_pdflinks_meetings

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


D = datetime.date

# ---- parse_date: full dates ------------------------------------------------
FULL = {
    '2026-07-21-Minutes': D(2026, 7, 21),
    '2026-09-17-Called-Meeting-x2': D(2026, 9, 17),
    'Meeting minutes 8-18-2026': D(2026, 8, 18),
    'Agenda for Commissioners Meeting 9-15-26': D(2026, 9, 15),
    'Combined-03-03-26-Agendas': D(2026, 3, 3),
    'Called-Meeting-01-27-26': D(2026, 1, 27),
    'Agenda-Commissioners-Meeting-July-21-2026-Regular-Meeting': D(2026, 7, 21),
    'Agenda-Commissioners-Meeting-2025-January-7-Regular-Meeting': D(2025, 1, 7),
    'September 16, 2025 agenda': D(2025, 9, 16),
    'July 21 26 minutes': D(2026, 7, 21),
    'April 21, 26 regular meeting': D(2026, 4, 21),
    'March 17 26 regular meeting agenda': D(2026, 3, 17),
    'APR-10-25Regular-Meeting-Minutes': D(2025, 4, 10),
    'Minutes-JUNE1225-Regualar-Meeting': D(2025, 6, 12),
    'Called-Meeting-JULY-29-25': D(2025, 7, 29),
    '2025-Sept-17-regular-meeting-minutes': D(2025, 9, 17),
    '051226-Combined': D(2026, 5, 12),
    '022625 Agenda': D(2025, 2, 26),
    '020625 hearing 6': D(2025, 2, 6),
    'Agenda-110723': D(2023, 11, 7),
    'Dec-05-24-Agendas': D(2024, 12, 5),
    '10-04-2022-Agenda': D(2022, 10, 4),
    'Commissioners Meeting 2-18-2025': D(2025, 2, 18),
    'November18 regular meeting minutes': None,   # month+day only: see MD below
}
for name, want in FULL.items():
    got = parse_date(name)
    if want is None:
        check('full: %s is not a full date' % name, got and got[0], 'md')
    else:
        check('full: %s' % name, got, ('full', want))

# ---- parse_date: month + day, year to be inferred ----------------------------
MD = {
    'Aug 17 work session agenda': (8, 17),
    'july 21 regular agenda': (7, 21),
    '4-2 called meeting agenda': (4, 2),
    '04-14-Agenda': (4, 14),
    'Dec 16 meeting minutes': (12, 16),
    'November18 regular meeting minutes': (11, 18),
    'march 18 minutes': (3, 18),
}
for name, want in MD.items():
    check('md: %s' % name, parse_date(name), ('md', want))

# ---- parse_date: deliberately NOT read -----------------------------------
for name in ['Oct 25 minutes', 'may 25 minutes', 'july25 minutes', 'Feb 26 minutes',
             '09-26-Minutes', '01-26-Minutes-Combined', '04-26-Combined', '03-25-Minutes',
             '122022-Minutes-Combined', '082022-Combined-Agendas', '012023-Combined-Agendas',
             'September 2025 minutes', '04-2025-Minutes', '06-2025-Combined-June-1',
             '2026-08-Combined-Minutes', 'Agendas-2025-10', 'Agenda-Combined-09-2025',
             'Agenda-2', 'agenda33', 'Meeting Agenda 520', 'Reg Meeting Agenda',
             'november regular meeting agenda', 'june minutes', '0125-Minutes-Combined',
             'mayor-agenda', 'Proposed-Budget-Summary-FY2027']:
    check('unreadable: %s' % name, parse_date(name), None)

# ---- year inference ----------------------------------------------------
check('latest-year: Dec after Jan rolls back a year',
      pdflinks._latest_year(12, 16, D(2026, 1, 20)), D(2025, 12, 16))
check('latest-year: Aug before Sept stays in year',
      pdflinks._latest_year(8, 17, D(2026, 8, 18)), D(2026, 8, 17))
check('latest-year: a meeting 3 weeks after the reference is allowed',
      pdflinks._latest_year(10, 8, D(2026, 9, 20)), D(2026, 10, 8))

TODAY = D(2026, 10, 30)


def page(*pairs):
    return ''.join('<a href="%s">%s</a>' % p for p in pairs)


# Bacon: flat /uploads/, newest first, years only on some names.
BACON = page(
    ('/uploads/Agenda for Commissioners Meeting 9-15-26.pdf', 'Agenda'),
    ('/uploads/Aug 17 work session agenda.pdf', 'Agenda'),
    ('/uploads/jan 20 26 minutes.pdf', 'Minutes'),
    ('/uploads/Dec 16 meeting minutes.pdf', 'Commissioner&rsquo;s Meeting - Minutes'),
    ('/uploads/Oct 25 minutes.pdf', 'Minutes'),
    ('/uploads/Agenda-2.pdf', 'Agenda'),
    ('/uploads/012125 meeting.pdf', 'Commissioner&rsquo;s Meeting - Minutes'),
    ('/uploads/ADA-notice.pdf', 'ADA Notice'),
)
st = {}
links = parse_page(BACON, 'https://baconcounty.org/minutes-agendas.php', year_from_order=True,
                   today=TODAY, stats=st)
got = {(d, k) for d, k, *_ in links}
check('bacon: dated by order', got, {('2026-09-15', 'agenda'), ('2026-08-17', 'agenda'),
                                     ('2026-01-20', 'minutes'), ('2025-12-16', 'minutes'),
                                     ('2025-01-21', 'minutes')})
check('bacon: unreadables counted, non-meeting PDFs not',
      (st['skipped_nodate'], st['skipped_nokind']), (2, 1))
check('bacon: spaces encoded in url',
      links[0][2], 'https://baconcounty.org/uploads/Agenda%20for%20Commissioners%20Meeting%209-15-26.pdf')

# Without year_from_order a yearless name is NOT guessed.
links = parse_page(BACON, 'https://baconcounty.org/minutes-agendas.php', year_from_order=False,
                   today=TODAY)
check('bacon: no inference when year_from_order is off',
      {d for d, *_ in links}, {'2026-09-15', '2026-01-20', '2025-01-21'})

# Appling: year comes from the upload path.
APPLING = page(
    ('https://applingcountyga.org/wp-content/uploads/2026/04/04-14-Agenda.pdf', 'Agenda'),
    ('https://applingcountyga.org/wp-content/uploads/2026/06/04-26-Combined.pdf', 'Minutes'),
    ('https://applingcountyga.org/wp-content/uploads/2026/01/Dec-09-Agenda.pdf', 'Agenda'),
    ('https://applingcountyga.org/wp-content/uploads/2026/05/051226-Combined.pdf', 'Agenda'),
    ('https://applingcountyga.org/wp-content/uploads/2026/05/051226-Combined.pdf', 'Minutes'),
    ('https://applingcountyga.org/wp-content/uploads/2026/04/2026-Manager-Contract.pdf', 'Contract'),
)
links = parse_page(APPLING, 'https://applingcountyga.org/?page_id=98', today=TODAY)
ms = build_meetings(links)
check('appling: upload-path year', [(m['date'], bool(m['agendaUrl']), bool(m['minutesUrl'])) for m in ms],
      [('2026-05-12', True, True), ('2026-04-14', True, False), ('2025-12-09', True, False)])

# Atkinson: http links on an https page are upgraded; text carries the month.
ATK = page(
    ('http://atkinsoncounty.org/wp-content/uploads/2025/04/APR-10-25Regular-Meeting-Minutes.pdf',
     'April 2025 Meeting Minutes'),
    ('http://atkinsoncounty.org/wp-content/uploads/2021/02/January-Meeting-Minutes.pdf',
     'January 2021 Meeting Minutes'),
)
links = parse_page(ATK, 'https://atkinsoncounty.org/board-meeting-minutes/', today=TODAY)
check('atkinson: one dated, month-year-only skipped', [(d, k) for d, k, *_ in links],
      [('2025-04-10', 'minutes')])
check('atkinson: http upgraded to https', links[0][2].startswith('https://atkinsoncounty.org/'), True)

# Kind: text beats file name; minutes beat agenda; action agenda yields to primary.
check('kind: text says minutes, name has none', pdflinks._classify('012125 meeting.pdf', 'Meeting - Minutes'),
      ('minutes', False))
check('kind: name fallback', pdflinks._classify('x/Agenda.pdf', ''), ('agenda', False))
check('kind: nothing', pdflinks._classify('x/notice.pdf', 'ADA'), (None, False))
ms = build_meetings([
    ('2026-05-12', 'agenda', 'https://h/action.pdf', True, 'Action Agenda'),
    ('2026-05-12', 'agenda', 'https://h/primary.pdf', False, 'Agenda'),
], body='BOC')
check('action agenda upgraded to primary', ms[0]['agendaUrl'], 'https://h/primary.pdf')
check('combined file fills both slots',
      (lambda m: (m['agendaUrl'], m['minutesUrl']))(build_meetings([
          ('2026-05-12', 'agenda', 'https://h/c.pdf', False, 'Agenda'),
          ('2026-05-12', 'minutes', 'https://h/c.pdf', False, 'Minutes')])[0]),
      ('https://h/c.pdf', 'https://h/c.pdf'))
check('title is body + date when the text is generic',
      build_meetings([('2026-05-12', 'agenda', 'https://h/a.pdf', False, 'Agenda')], body='BOC')[0]['title'],
      'BOC 2026-05-12')
check('title keeps a meaningful label',
      build_meetings([('2026-05-12', 'minutes', 'https://h/a.pdf', False, 'Public Hearing - Minutes')],
                     body='BOC')[0]['title'], 'Public Hearing')
check('newest first', [m['date'] for m in build_meetings([
    ('2025-01-01', 'agenda', 'https://h/a', False, ''), ('2026-01-01', 'agenda', 'https://h/b', False, '')])],
    ['2026-01-01', '2025-01-01'])

# ---- fetch: all-or-nothing across pages ---------------------------------
real = pdflinks.fetch_bytes
calls = []


def fake(url, **kw):
    calls.append(url)
    if 'bad' in url:
        return None
    return ATK.encode()


pdflinks.fetch_bytes = fake
try:
    ms, bodies = fetch_pdflinks_meetings('https://atkinsoncounty.org/good',
                                         extra_urls=['https://atkinsoncounty.org/bad'])
    check('a failed extra page fails the whole fetch', (ms, bodies), (None, None))
    ms, bodies = fetch_pdflinks_meetings('https://atkinsoncounty.org/good',
                                         extra_urls=['https://atkinsoncounty.org/good2'],
                                         body='Board of Commissioners')
    check('two pages merge by date', ([m['date'] for m in ms], bodies),
          (['2025-04-10'], ['Board of Commissioners']))
finally:
    pdflinks.fetch_bytes = real

print()
if failures:
    print('%d FAILED: %s' % (len(failures), ', '.join(failures)))
    sys.exit(1)
print('all passed')
