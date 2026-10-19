#!/usr/bin/env python3
"""Invariants of the AgendaPlus adapter (lib/agendaplus.py).

The source is a static HTML list page, so the fixture below reproduces the real
Savannah markup, including the one trap that makes it dangerous to parse with an
HTML parser: an empty minutes cell is emitted SELF-CLOSING (`<td class="minutelink" />`),
which a tolerant parser reads as an open cell swallowing the following row.

Pinned here: cells are read by class, relative hrefs resolve against the list
page, the body is the title minus its leading date, a self-closing minutes cell
is None and does not eat the next row, a direct-PDF minutes link survives,
link-less/date-less rows are dropped, duplicate ids collapse, output is
newest-first, and a failed fetch is (None, None).

Run: python scripts/test_agendaplus.py       (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.agendaplus import fetch_agendaplus_meetings, parse_agendaplus_list

PAGE = 'https://agenda.example.gov/publishing/ap-agendas.html'
failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


FIXTURE = """
<table class="table"><thead><tr><th>Date</th><th>Title</th></tr></thead><tbody>
  <tr ID="1593" class="flRow October2026">
    <td class="meetingdate">October 22, 2026</td>
    <td class="title">October 22, 2026 City Council Regular Meeting</td>
    <td class="agendalink">
      <a href="october-22-2026-city-council-regular-meeting/agenda.html" target="_blank">Agenda</a>
    </td>
    <td class="minutelink" />
  </tr>
  <tr ID="1606" class="flRow October2026">
    <td class="meetingdate">October 22, 2026</td>
    <td class="title">October 22, 2026 City Council Workshop</td>
    <td class="agendalink">
      <a href="october-22-2026-city-council-workshop/agenda.html">Agenda</a>
    </td>
    <td class="minutelink" />
  </tr>
  <tr ID="1400" class="flRow April2020">
    <td class="meetingdate">April 09, 2020</td>
    <td class="title">April 9, 2020 City Council Regular Meeting</td>
    <td class="agendalink"><a href="april-09-2020-city-council-regular-meeting/agenda.html">Agenda</a></td>
    <td class="minutelink"><a href="april-09-2020-city-council-regular-meeting/minutes.pdf">Minutes</a></td>
  </tr>
  <tr ID="1300" class="flRow April2019">
    <td class="meetingdate">April 11, 2019</td>
    <td class="title">April 11, 2019 City Council Workshop</td>
    <td class="agendalink" />
    <td class="minutelink"><a href="april-11-2019-city-council-workshop/minutes.html">Minutes</a></td>
  </tr>
  <tr ID="1299" class="flRow April2019">
    <td class="meetingdate">April 11, 2019</td>
    <td class="title">April 11, 2019 Placeholder with no links</td>
    <td class="agendalink" />
    <td class="minutelink" />
  </tr>
  <tr ID="1298" class="flRow">
    <td class="meetingdate">not a date</td>
    <td class="title">Garbled</td>
    <td class="agendalink"><a href="x/agenda.html">Agenda</a></td>
    <td class="minutelink" />
  </tr>
  <tr ID="1593" class="flRow October2026">
    <td class="meetingdate">October 22, 2026</td>
    <td class="title">October 22, 2026 City Council Regular Meeting</td>
    <td class="agendalink"><a href="dup/agenda.html">Agenda</a></td>
    <td class="minutelink" />
  </tr>
</tbody></table>
"""

ms = parse_agendaplus_list(FIXTURE, PAGE)
by_id = {m['id']: m for m in ms}

check('placeholder, garbled-date and duplicate rows dropped', sorted(by_id), ['1300', '1400', '1593', '1606'])

reg = by_id['1593']
check('relative agenda href resolves against the list page',
      reg['agendaUrl'],
      'https://agenda.example.gov/publishing/october-22-2026-city-council-regular-meeting/agenda.html')
check('first row wins over a duplicate id', 'dup/' in reg['agendaUrl'], False)
check('self-closing minutes cell is None', reg['minutesUrl'], None)
check('self-closing cell does not swallow the next row',
      by_id['1606']['title'], 'October 22, 2026 City Council Workshop')
check('date is ISO', reg['date'], '2026-10-22')
check('body is the title minus its leading date', reg['body'], 'City Council Regular Meeting')
check('title keeps the full text', reg['title'], 'October 22, 2026 City Council Regular Meeting')
check('single-digit day in title still strips', by_id['1400']['body'], 'City Council Regular Meeting')
check('direct-PDF minutes link kept',
      by_id['1400']['minutesUrl'],
      'https://agenda.example.gov/publishing/april-09-2020-city-council-regular-meeting/minutes.pdf')
check('minutes-only meeting is kept with agenda None',
      (by_id['1300']['agendaUrl'], bool(by_id['1300']['minutesUrl'])), (None, True))
check('video not exposed', reg['videoUrl'], None)

meetings, bodies = fetch_agendaplus_meetings(
    PAGE, fetcher=lambda url, **kw: FIXTURE.encode('utf-8'))
check('newest first, id breaks same-day ties descending',
      [m['id'] for m in meetings], ['1606', '1593', '1400', '1300'])
check('bodies sorted and distinct', bodies, ['City Council Regular Meeting', 'City Council Workshop'])

check('failed fetch -> (None, None)',
      fetch_agendaplus_meetings(PAGE, fetcher=lambda url, **kw: None), (None, None))
empty, _ = fetch_agendaplus_meetings(PAGE, fetcher=lambda url, **kw: b'<html>changed</html>')
check('reskinned page parses to [] (caller treats as hard failure)', empty, [])

if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All AgendaPlus checks passed.')
