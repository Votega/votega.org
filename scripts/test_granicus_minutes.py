#!/usr/bin/env python3
"""Granicus ViewPublisher rows: minutes links in BOTH known forms are captured.

Spalding links minutes to an absolute /services/minutes/reports/<uuid>/attachment
URL, not MinutesViewer.php; the old regex matched only the latter, so all 298 of
Spalding's past meetings published as agenda-only.

Run: python scripts/test_granicus_minutes.py      (no network)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.granicus import _parse_row

SVC = ('https://spaldingcounty.granicus.com/services/minutes/reports/'
       'cc5a424c-2f35-44ef-beb2-7fe65879dea4/attachment')
ROW_SVC = '\n'.join([
    '<tr class="listingRow">',
    '<td class="listItem" headers="Name" scope="row">Board of Assessors</td>',
    '<td class="listItem" headers="Date Board-of-Assessors">'
    'Mar&nbsp;11,&nbsp;2025 - 09:00&nbsp;AM</td>',
    '<td class="listItem"><a href="//spaldingcounty.granicus.com/AgendaViewer.php'
    '?view_id=1&event_id=772">Agenda</a></td>',
    '<td class="listItem"><a href="%s" target="_blank">Minutes</a></td></tr>' % SVC,
])
ROW_OLD = ROW_SVC.replace(
    SVC, '//x.granicus.com/MinutesViewer.php?view_id=1&clip_id=5')
ROW_NONE = ROW_SVC.replace('<a href="%s" target="_blank">Minutes</a>' % SVC, '')

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


check('service-form minutes', _parse_row(ROW_SVC, 'https')['minutesUrl'], SVC)
check('agenda still parsed', bool(_parse_row(ROW_SVC, 'https')['agendaUrl']), True)
check('viewer-form minutes',
      _parse_row(ROW_OLD, 'https')['minutesUrl'],
      'https://x.granicus.com/MinutesViewer.php?view_id=1&clip_id=5')
check('no minutes', _parse_row(ROW_NONE, 'https')['minutesUrl'], None)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
