#!/usr/bin/env python3
"""Legistar meeting-detail scrape: minutes/video links the Web API leaves null.

Run: python scripts/test_legistar_detail_links.py      (no network)
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.legistar import apply_detail_links, parse_detail_links

URL = 'https://fulton.legistar.com/MeetingDetail.aspx?LEGID=1'
WITH = ('<a id="ctl00_hypMinutes" href="View.ashx?M=M&amp;ID=9&amp;G=X" style="c">'
        '<a id="ctl00_hypVideo" class="videolink" onclick="window.open(&#39;'
        'Video.aspx?Mode=Granicus&amp;ID1=460&amp;G=X&amp;Mode2=Video&#39;,'
        '&#39;video&#39;);return false;" href="#">')
GREY = ('<a id="ctl00_hypMinutes" class="minuteNotAvaliableLink" style="c">'
        '<a id="ctl00_hypVideo" class="videolink" onclick="window.open(&#39;'
        'Video.aspx?Mode=Granicus&amp;ID1=5&amp;G=X&amp;Mode2=Video&#39;);" href="#">')
failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


check('both', parse_detail_links(WITH, URL), (
    'https://fulton.legistar.com/View.ashx?M=M&ID=9&G=X',
    'https://fulton.legistar.com/Video.aspx?Mode=Granicus&ID1=460&G=X&Mode2=Video'))
m, v = parse_detail_links(GREY, URL)
check('greyed-out minutes is None', m, None)
check('video still found', bool(v), True)
check('empty page', parse_detail_links('<html></html>', URL), (None, None))

TODAY = dt.date(2026, 11, 1)


def mk(i, date, minutes=None, video=None):
    return {'id': i, 'date': date, 'minutesUrl': minutes, 'videoUrl': video}


calls = []


def fake(url):
    calls.append(url)
    return ('M:' + url, 'V:' + url)


ms = [mk('1', '2026-10-20'),            # recent, no links -> fetched
      mk('2', '2025-01-01'),            # old, unseen      -> fetched once
      mk('3', '2025-01-01'),            # old, in previous -> carried forward
      mk('4', '2026-12-01'),            # future           -> skipped
      mk('5', '2026-10-01', 'a', 'b')]  # complete         -> skipped
prev = [dict(mk('3', '2025-01-01', 'pm', 'pv'), detailChecked=True),
        mk('2', '2025-01-01')]   # in previous but never detail-checked -> fetched
urls = {str(i): 'u%d' % i for i in range(1, 6)}
n = apply_detail_links(ms, urls, prev, TODAY, fetch=fake)
check('fetch count', (n, sorted(calls)), (2, ['u1', 'u2']))
check('carried forward', (ms[2]['minutesUrl'], ms[2]['videoUrl']), ('pm', 'pv'))
check('future untouched', ms[3]['minutesUrl'], None)

ms = [mk('1', '2026-10-20', 'api-min')]
apply_detail_links(ms, {'1': 'u'}, None, TODAY, fetch=lambda u: (None, 'vid'))
check('api value wins, gaps filled', (ms[0]['minutesUrl'], ms[0]['videoUrl']),
      ('api-min', 'vid'))
ms = [mk('1', '2026-10-20')]
apply_detail_links(ms, {'1': 'u'}, None, TODAY, fetch=lambda u: None)
check('failed fetch leaves record', ms[0]['minutesUrl'], None)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
