#!/usr/bin/env python3
"""Invariants of the Municode Meetings pager (lib/teammunicode.py, max_pages).

Augusta-Richmond's front page is a ~7-week window; the rest sits behind
`?page=N`. The host also answers a burst with HTTP 200 + an HAProxy captcha page,
which has no meeting rows and so looks exactly like "past the last page".

Pinned here: max_pages=1 (the default) fetches one URL, pages are walked in order
and merged newest-first with seam duplicates collapsed, an empty page ends the walk,
a captcha page or a failed later page returns (None, None) rather than a truncated
archive, and the walk never exceeds max_pages.

Run: python scripts/test_teammunicode_pager.py       (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lib.teammunicode as tm

tm.PAGE_DELAY = 0
BASE = 'https://example.municodemeetings.com'
failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def row(date, n):
    return ('<tr><td class="views-field-title"><a href="/bc-commission/page/commission-meeting-%d">'
            'Commission Meeting</a></td><td><span class="date-display-single" content="%sT14:00:00-04:00">'
            'x</span></td><td class="views-field-field-agendas"><a href="https://f/%d.pdf">A</a></td></tr>'
            % (n, date, n))


PAGES = {
    0: '<table>' + row('2026-03-10', 3) + row('2026-03-03', 2) + '</table>',
    1: '<table>' + row('2026-03-03', 2) + row('2026-02-24', 1) + '</table>',  # seam dup
    2: '<table></table>',
}
CHALLENGE = '<html><title>HAProxy Challenge</title></html>'


def make_fetcher(pages, calls):
    def fetch(url, **kw):
        calls.append(url)
        n = int(url.split('page=')[1]) if 'page=' in url else 0
        body = pages.get(n)
        return None if body is None else body.encode()
    return fetch


real = tm.fetch_bytes

calls = []
tm.fetch_bytes = make_fetcher(PAGES, calls)
m, _ = tm.fetch_teammunicode_meetings(BASE, meetings_path='/')
check('default fetches exactly one page', (len(calls), len(m)), (1, 2))

calls.clear()
m, b = tm.fetch_teammunicode_meetings(BASE, meetings_path='/', max_pages=8)
check('walks until an empty page, then stops', len(calls), 3)
check('seam duplicate collapsed, newest first', [x['id'] for x in m], ['3', '2', '1'])
check('pager url', calls[1], BASE + '/?page=1')

calls.clear()
m, _ = tm.fetch_teammunicode_meetings(BASE, meetings_path='/', max_pages=2)
check('never exceeds max_pages', (len(calls), len(m)), (2, 3))

tm.fetch_bytes = make_fetcher({0: PAGES[0], 1: CHALLENGE}, [])
check('captcha page mid-walk -> (None, None)',
      tm.fetch_teammunicode_meetings(BASE, meetings_path='/', max_pages=8), (None, None))

tm.fetch_bytes = make_fetcher({0: PAGES[0]}, [])  # page 1 -> None (fetch failure)
check('failed later page -> (None, None), not a partial list',
      tm.fetch_teammunicode_meetings(BASE, meetings_path='/', max_pages=8), (None, None))

tm.fetch_bytes = real
if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All Municode pager checks passed.')
