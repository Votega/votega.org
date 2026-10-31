#!/usr/bin/env python3
"""Invariants of the SharePoint library adapter (lib/sharepoint.py) and of how the PDF
enricher uses it. No network, no browser.

The file names are LaFayette's real 2026 listing (15 agendas, 15 minutes).

What is pinned, and why:
  * Dates come from the three two-digit numbers in the name, and the leftover words are
    the meeting's label (`MINUTES 05 22 26 SPECIAL CALLED.pdf` -> Special Called).
  * Minutes pair with the agenda of the same date and label; 8/10 has a regular meeting
    AND a public hearing that day and stays two meetings, with the hearing's minutes
    not attached to the regular agenda.
  * The links we PUBLISH are the folder share, never a direct file URL (a visitor with
    no session is sent to a Microsoft sign-in); the direct URLs are separate fields.
  * The enricher reads the direct file through the session but writes the PUBLIC link
    into the sidecar, and keys its cache on the file URL.
  * A library that lists nothing, or whose names carry no date, refuses rather than
    publish an empty or undated meeting list.

Run: python scripts/test_sharepoint.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import sharepoint as S  # noqa: E402
import enrich_ocr_meetings as E  # noqa: E402

SHARE = 'https://cityoflafayettega.sharepoint.com/:f:/g/citycouncil/TOKEN?e=x'
AGENDAS = ['0 AGENDA %s.pdf' % d for d in (
    '01 02 26', '01 12 26', '02 09 26', '03 09 26', '04 13 26', '04 17 26', '05 11 26',
    '05 22 26', '06 08 26', '07 07 26', '08 10 26', '08 25 26', '09 14 26', '09 24 26',
    '10 20 26')]
MINUTES = ['MINUTES 01 02 26.pdf', 'MINUTES 01 12 26.pdf', 'MINUTES 02 09 26.pdf',
           'MINUTES 03 09 26.pdf', 'MINUTES 04 13 26.pdf',
           'MINUTES 04 17 26 SPECIAL CALLED.pdf', 'MINUTES 05 11 26.pdf',
           'MINUTES 05 22 26 SPECIAL CALLED.pdf', 'MINUTES 06 08 26.pdf',
           'MINUTES 07 07 26.pdf', 'MINUTES 08 10 26 PUBLIC HEARING.pdf',
           'MINUTES 08 10 26.pdf', 'MINUTES 08 25 26 SPECIAL CALLED MEETING.pdf',
           'MINUTES 09 14 26.pdf', 'MINUTES 09 24 26 SPECIAL CALLED MEETING.pdf']

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


def files(names, folder):
    return [{'name': n, 'url': 'https://sp.example/lib/%s/%s' % (folder, n.replace(' ', '%20'))}
            for n in names]


meetings, rep = S.parse_listing(files(AGENDAS, 'A'), files(MINUTES, 'M'), SHARE)
by = {m['id']: m for m in meetings}

print('File names')
check(S.parse_name('0 AGENDA 10 20 26.pdf') == ('2026-10-20', ''), 'agenda name -> date, no label')
check(S.parse_name('MINUTES 05 22 26 SPECIAL CALLED.pdf') == ('2026-05-22', 'Special Called'),
      'minutes name -> date + label')
check(S.parse_name('MINUTES 13 40 26.pdf') is None, 'an impossible date is not guessed')
check(S.parse_name('Budget Summary.pdf') is None, 'no date -> None')

print('Meetings')
check(len(meetings) == 16 and rep['skipped'] == [], '30 files -> 16 meetings, none skipped')
check([m['date'] for m in meetings] == sorted((m['date'] for m in meetings), reverse=True),
      'newest first')
oct20 = by['2026-10-20-council-meeting']
check(oct20['agendaUrl'] and oct20['minutesUrl'] is None and oct20['minutesFileUrl'] is None,
      'an agenda with no minutes yet leaves minutes None')
check(by['2026-04-17-special-called']['minutesUrl'] and by['2026-04-17-special-called']['agendaUrl'],
      'a lone labelled minutes file pairs with the lone agenda of its date')
check('2026-08-10-public-hearing' in by and by['2026-08-10-public-hearing']['agendaUrl'] is None,
      'a hearing that day stays its own meeting, with minutes only')
reg = by['2026-08-10-council-meeting']
check(reg['agendaUrl'] and reg['minutesUrl'] and reg['minutesFileUrl'].endswith('MINUTES%2008%2010%2026.pdf'),
      'the regular 8/10 agenda pairs with the unlabelled minutes, not the hearing\'s')
check(by['2026-09-24-special-called-meeting']['title'] == 'September 24, 2026 Special Called Meeting',
      'title: %r' % by['2026-09-24-special-called-meeting']['title'])
check(by['2026-05-22-special-called']['title'] == 'May 22, 2026 Special Called Meeting',
      'a label without "meeting" gets it appended')

print('Links')
check(all(m['agendaUrl'] in (None, SHARE) and m['minutesUrl'] in (None, SHARE) for m in meetings),
      'published links are the folder share (or None), never a direct file')
check(all((m['agendaUrl'] is None) == (m['agendaFileUrl'] is None) for m in meetings),
      'a direct file URL exists exactly when an agenda link does')

print('Failure modes')
check(raises(lambda: S.parse_listing([], [], SHARE), 'no files'), 'empty library -> refuse')
check(raises(lambda: S.parse_listing(files(['Cover.pdf'], 'A'), [], SHARE), 'carried a date'),
      'no dated names -> refuse')

print('Fetch wrapper')


class FakeSession:
    def __init__(self, share_url):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def list_folder(self, sub):
        return files(AGENDAS if sub == 'Council Agendas' else MINUTES, sub)


got, bodies = S.fetch_sharepoint_meetings(SHARE, 'Council Agendas', 'Council Minutes',
                                          session_factory=FakeSession)
check(got is not None and len(got) == 16 and bodies == ['City Council'], 'listing via a session')


class Broken(FakeSession):
    def list_folder(self, sub):
        raise RuntimeError('boom')


got, bodies = S.fetch_sharepoint_meetings(SHARE, 'a', 'b', session_factory=Broken)
check(got is None and bodies is None, 'a library that cannot be read returns (None, None)')

print('Enricher plumbing')
m = {'id': 'x', 'agendaUrl': SHARE, 'minutesUrl': None,
     'agendaFileUrl': 'https://sp.example/lib/A/0%20AGENDA.pdf', 'minutesFileUrl': None}
check(E.text_source(m) == ('https://sp.example/lib/A/0%20AGENDA.pdf', 'agenda'),
      'the file URL, not the folder link, is what is read')
check(E.text_source({'id': 'y', 'agendaUrl': 'https://c/a.pdf', 'minutesUrl': None}) ==
      ('https://c/a.pdf', 'agenda'), 'an ordinary place is unchanged')
check(E.text_source({'id': 'z', 'agendaUrl': None, 'minutesUrl': SHARE,
                     'minutesFileUrl': 'https://sp.example/M.pdf'}) == ('https://sp.example/M.pdf', 'minutes'),
      'minutes fall back the same way')

calls = []
E.extract_text = lambda path: ('rezoning of 40 acres for a data center', 'pdftotext')
rec = E.enrich_meeting(dict(m, date='2026-10-20', title='October 20, 2026 Council Meeting', body='City Council'),
                       {}, slug='t', session_fetch=lambda u: calls.append(u) or b'%PDF-fake')
check(calls == ['https://sp.example/lib/A/0%20AGENDA.pdf'], 'the session fetched the direct file URL')
check(rec['sourceUrl'] == SHARE and rec['textSourceUrl'] == 'https://sp.example/lib/A/0%20AGENDA.pdf',
      'sidecar links the PUBLIC folder; the cache key is the file URL')
check(rec['dataCenterItems'] and rec['dataCenterItems'][0]['sourceUrl'] == SHARE,
      'a flagged item links the public folder, never a link a visitor cannot open')
again = E.enrich_meeting(dict(m, date='2026-10-20'), {'x': rec}, slug='t',
                         session_fetch=lambda u: calls.append('REFETCH') or b'x')
check(again is rec and 'REFETCH' not in calls, 'an unchanged file is not downloaded again')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll SharePoint adapter invariants hold.')
