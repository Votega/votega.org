#!/usr/bin/env python3
"""Invariants of generate_georgia_commons_links.py. No network, no pip packages.

What is pinned, and why:
  * The join is the Simbli (S, MID) pair, never the date: two meetings of one board
    on one day (work session + regular session) must not cross-link, and a meeting
    on another Simbli site with the same MID must not link either.
  * Only minutes sources count, and only georgiacommons.org page URLs are stored.
  * A failed API read keeps the district's previous links and is reported as
    failed (exit 1 from main), never written as "no summaries".
  * A link we had is not dropped because one run did not see it.
  * A link whose meeting we no longer hold is dropped (no row to hang it on).
  * The AI summary text (`headline`) is never stored: license not settled.

Run: python scripts/test_generate_georgia_commons_links.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_georgia_commons_links as G  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


VIEW = 'https://simbli.eboardsolutions.com/SB_Meetings/ViewMeeting.aspx?S=%s&MID=%s'


def ours(rows):
    return {'metadata': {}, 'meetings': [
        {'id': mid, 'date': date, 'title': 't', 'agendaUrl': VIEW % (s, mid),
         'minutesUrl': (VIEW % (s, mid)) + '&T=1'} for s, mid, date in rows]}


def gc(mid, s='4122', date='2026-08-20', district='707', slug='x', kind='minutes',
       url=None):
    return {'id': slug, 'date': date,
            'url': url or 'https://georgiacommons.org/meetings/%s/%s' % (date, slug),
            'jurisdiction': {'district_code': district},
            'headline': 'AI TEXT THAT MUST NOT BE STORED',
            'sources': [{'kind': kind, 'url': (VIEW % (s, mid)) + '&T=1'}]}


def fake(pages):
    """pages: {district: [meetings]} served one page at a time (PAGE=2 below)."""
    calls = []

    def fetch(url, **_):
        calls.append(url)
        q = dict(p.split('=') for p in url.split('?', 1)[1].split('&'))
        d = q['district_code']
        if pages.get(d) is None:
            return None
        off = int(q['offset'])
        chunk = pages[d][off:off + G.PAGE]
        nxt = off + G.PAGE if off + G.PAGE < len(pages[d]) else None
        return {'meetings': chunk, 'total': len(pages[d]), 'next_offset': nxt}
    fetch.calls = calls
    return fetch


def setup(tmp, files):
    for d, rows in files.items():
        with open(os.path.join(tmp, 'school-%s-meetings.json' % d), 'w', encoding='utf-8') as f:
            json.dump(ours(rows), f)


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
G.PAGE = 2

print('simbli_key')
check(G.simbli_key(VIEW % ('4122', '138515') + '&T=1') == ('4122', '138515'), 'parses S and MID')
check(G.simbli_key('https://simbli.eboardsolutions.com/index.aspx?s=4072&mid=9') == ('4072', '9'),
      'case-insensitive keys')
check(G.simbli_key('https://example.org/?S=1&MID=2') is None, 'non-Simbli host rejected')
check(G.simbli_key(None) is None, 'None is safe')

print('exact join')
with tempfile.TemporaryDirectory() as tmp:
    setup(tmp, {'707': [('4122', '100', '2026-08-20'), ('4122', '101', '2026-08-20')]})
    out = os.path.join(tmp, 'gc.json')
    meetings = [
        gc('100', slug='work-session'),
        gc('101', s='9999', slug='other-site'),       # same MID space, wrong site
        gc('102', slug='not-ours'),                   # a meeting we do not hold
        gc('101', kind='agenda', slug='agenda-only'),  # not a minutes source
        gc('101', url='https://evil.example/x'),     # off-host page
        gc('100', district='605', slug='wrong-district'),
    ]
    failed = G.run(data_dir=tmp, out_path=out, fetch=fake({'707': meetings}), now=NOW)
    data = json.load(open(out, encoding='utf-8'))
    links = data['districts']['707']
    check(failed == [], 'no failure')
    check(list(links) == ['100'], 'only the exactly matching meeting is linked')
    check(links['100']['url'].endswith('/work-session'), 'links its own page, not a same-day one')
    check('AI TEXT' not in json.dumps(data), 'headline text is never stored')
    check(data['metadata']['count'] == 1 and data['metadata']['carriedForward'] is None,
          'metadata count and no carry')

print('pagination')
with tempfile.TemporaryDirectory() as tmp:
    setup(tmp, {'707': [('4122', str(i), '2026-01-01') for i in range(1, 6)]})
    out = os.path.join(tmp, 'gc.json')
    f = fake({'707': [gc(str(i), slug='m%s' % i) for i in range(1, 6)]})
    G.run(data_dir=tmp, out_path=out, fetch=f, now=NOW)
    check(len(json.load(open(out, encoding='utf-8'))['districts']['707']) == 5,
          'every page read (5 meetings over 3 pages)')
    check(len(f.calls) == 3, 'stops when next_offset is null')

print('failure keeps previous links')
with tempfile.TemporaryDirectory() as tmp:
    setup(tmp, {'707': [('4122', '100', '2026-08-20')], '605': [('4007', '7', '2026-11-10')]})
    out = os.path.join(tmp, 'gc.json')
    G.run(data_dir=tmp, out_path=out, now=NOW,
          fetch=fake({'707': [gc('100')], '605': [gc('7', s='4007', district='605')]}))
    failed = G.run(data_dir=tmp, out_path=out, now=NOW,
                   fetch=fake({'707': None, '605': [gc('7', s='4007', district='605')]}))
    data = json.load(open(out, encoding='utf-8'))
    check(failed == ['707'], 'failed district reported')
    check('100' in data['districts']['707'], 'its previous link is kept')
    check(data['metadata']['carriedForward'] == ['707'], 'named under carriedForward')
    check('7' in data['districts']['605'], 'healthy district still written')

print('links are sticky, but follow our rows')
with tempfile.TemporaryDirectory() as tmp:
    setup(tmp, {'707': [('4122', '100', '2026-08-20'), ('4122', '101', '2026-08-21')]})
    out = os.path.join(tmp, 'gc.json')
    G.run(data_dir=tmp, out_path=out, now=NOW,
          fetch=fake({'707': [gc('100', slug='a'), gc('101', slug='b')]}))
    G.run(data_dir=tmp, out_path=out, now=NOW, fetch=fake({'707': [gc('101', slug='b')]}))
    check('100' in json.load(open(out, encoding='utf-8'))['districts']['707'],
          'a link not seen this run is kept')
    setup(tmp, {'707': [('4122', '101', '2026-08-21')]})
    G.run(data_dir=tmp, out_path=out, now=NOW, fetch=fake({'707': [gc('101', slug='b')]}))
    check(list(json.load(open(out, encoding='utf-8'))['districts']['707']) == ['101'],
          'a link whose meeting left our file is dropped')

if failures:
    print('\n%d FAILED' % len(failures))
    sys.exit(1)
print('\nall ok')
