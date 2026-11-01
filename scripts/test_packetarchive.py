#!/usr/bin/env python3
"""Invariants of the current-packet archiver (lib/packetarchive.py). No network.

Pinned, and why:
  * The link is resolved through its redirect and the REAL file is hashed/archived;
    the city's own link is what stays published while it works.
  * The date is the packet's own text when it names the month, else the registry's
    usual day, and `dateSource` says which - an inference is never silent.
  * A run that sees the next month's packet keeps the previous one, re-pointed at
    its archived copy, with the city's dead link kept in `agendaOriginalUrl`.
  * An unchanged packet is not downloaded or archived again.
  * Archiving is never faked: no archive copy means None, and a file we could not
    download is not sent to the archive.
  * An unreadable page returns (None, None); a page with no packet link keeps history.

Run: python scripts/test_packetarchive.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import packetarchive as P  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


PAGE = 'https://city.example'
CDN = 'https://cdn.example/t/1/Agenda+Packet+October+2026.pdf'


def page(*names):
    return ('<html><body>' + ''.join('<a href="/s/%s">Download</a>' % n for n in names)
            + '</body></html>').encode()


class Net:
    def __init__(self):
        self.fetched, self.archived = [], []
        self.fail_fetch = False

    def fetch(self, url):
        self.fetched.append(url)
        return None if self.fail_fetch else b'%PDF-1.4 packet ' + url.encode()

    def resolve(self, url):
        return CDN if 'October' in url else url.replace('/s/', '/cdn/')

    def archive(self, url):
        self.archived.append(url)
        return 'https://web.archive.org/web/2026/' + url


def run(net, names, previous=None, text='', **kw):
    return P.fetch_packetarchive_meetings(
        PAGE + '/council', body='City Council', meeting_nth=2, meeting_weekday=0,
        previous=previous, fetcher=net.fetch, resolver=net.resolve, archiver=net.archive,
        pdf_text=lambda b: text, page_fetcher=lambda u: page(*names) if names is not None else None,
        now='2026-11-01T00:00:00Z', **kw)


print('Parsing')
check(P.month_year('Agenda-Packet-October-2026.pdf') == (2026, 10), 'month/year from a packet name')
check(P.month_year('Agenda+Packet+October+2026.pdf') == (2026, 10), 'a plus-spaced CDN name too')
check(P.month_year('Budget-FY27.pdf') is None, 'no month+year -> None')
check(str(P.nth_weekday(2026, 10, 2, 0)) == '2026-10-12', '2nd Monday of Oct 2026')
check(P.date_from_text('Meeting of October 12, 2026; minutes of September 14, 2026', 2026, 10).day == 12,
      'only the named month counts as the meeting date')
check(P.date_from_text('minutes of September 14, 2026', 2026, 10) is None, 'a different month is ignored')
check(len(P.packet_links(page('Agenda-Packet-October-2026.pdf', 'Budget.pdf').decode(), PAGE)) == 1,
      'links without a month+year are not packets')

print('First sighting')
net = Net()
ms, bodies = run(net, ['Agenda-Packet-October-2026.pdf'])
m = ms[0]
check(len(ms) == 1 and bodies == ['City Council'], 'one meeting, one body')
check(m['agendaUrl'] == PAGE + '/s/Agenda-Packet-October-2026.pdf', "the city's link stays published")
check(m['agendaFileUrl'] == CDN and net.fetched == [CDN] and net.archived == [CDN],
      'the redirect target is what is downloaded and archived')
check(m['agendaSha256'] and m['agendaBytes'] and m['agendaFetchedAt'] == '2026-11-01T00:00:00Z',
      'hash, size and fetch time are recorded')
check(m['date'] == '2026-10-12' and m['dateSource'] == 'schedule rule', 'rule date, labelled as such')
check(m['id'] == '2026-10-city-council', 'id is year-month-body')
ms2, _ = run(Net(), ['Agenda-Packet-October-2026.pdf'], text='Regular Meeting October 19, 2026')
check(ms2[0]['date'] == '2026-10-19' and ms2[0]['dateSource'] == 'packet text',
      "the packet's own date beats the rule")

print('A later run')
net2 = Net()
ms3, _ = run(net2, ['Agenda-Packet-October-2026.pdf'], previous=ms)
check(net2.fetched == [] and net2.archived == [], 'an unchanged packet is not fetched or archived again')
check(ms3[0]['agendaSha256'] == m['agendaSha256'], 'its hash is carried over')

net3 = Net()
ms4, _ = run(net3, ['Agenda-Packet-November-2026.pdf'], previous=ms)
by = {x['id']: x for x in ms4}
old, new = by['2026-10-city-council'], by['2026-11-city-council']
check(len(ms4) == 2 and ms4[0]['id'] == '2026-11-city-council', 'history is kept, newest first')
check(old['agendaUrl'] == m['agendaArchiveUrl'] and old['agendaOriginalUrl'] == m['agendaUrl'],
      "the replaced packet points at its archive; the city's link is kept as the original")
check(new['agendaUrl'].endswith('Agenda-Packet-November-2026.pdf'), "the new packet shows the city's link")
check(net3.fetched == [PAGE + '/cdn/Agenda-Packet-November-2026.pdf'], 'only the new file is downloaded')

print('Honest failure modes')
net4 = Net()
net4.fail_fetch = True
ms5, _ = run(net4, ['Agenda-Packet-October-2026.pdf'])
check(ms5[0]['agendaSha256'] is None and net4.archived == [] and ms5[0]['agendaArchiveUrl'] is None,
      'a file we could not download is neither hashed nor sent to the archive')
check(run(Net(), None)[0] is None, 'an unreadable page returns (None, None)')
kept, _ = run(Net(), [], previous=ms)
check(kept and kept[0]['id'] == '2026-10-city-council', 'a page with no packet link keeps the earlier record')
check(run(Net(), [])[0] is None, 'no link and no history -> (None, None)')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll packet-archive invariants hold.')
