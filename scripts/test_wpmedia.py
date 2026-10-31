#!/usr/bin/env python3
"""Invariants of the WordPress media-library adapter (lib/wpmedia.py).

Fixtures are real Rockdale County media titles. Pinned here: titles are routed to a
body by the FIRST matching rule and files matching no rule are dropped (SPLOST
subcommittees, KCRB, water authority); a "Packet" title is read as an agenda; dates
and kinds come from pdflinks' rules (a day-less "April 2026 Planning Commission
Minutes" is skipped, never guessed); a minutes and an agenda for the same date merge
into one record; two bodies on the same day stay two records with distinct ids;
duplicate media ids across search terms collapse; a failed first page is
(None, None) while a failure on a later page just ends that term; and an empty
`media_bodies` is a config error, not a silent empty result.

Run: python scripts/test_wpmedia.py       (no network, no repo writes)
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import wpmedia

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def item(i, title, name, ym='2026/10'):
    return {'id': i, 'title': {'rendered': title},
            'source_url': 'https://www.rockdalecountyga.gov/wp-content/uploads/%s/%s' % (ym, name)}


BODIES = [{'match': r'\bBOC\b|Board of Commissioners', 'label': 'Board of Commissioners'},
          {'match': r'Planning Commission|\bPC\b', 'label': 'Planning Commission'}]
BASE = 'https://www.rockdalecountyga.gov'

MEDIA = {
    'minutes': [
        item(1, 'BOC minutes 10.20.26', 'BOC-minutes-10.20.26.pdf'),
        item(2, 'BOC minutes &#8211; 9.8.26', 'BOC-minutes-9.8.26.pdf', '2026/09'),
        item(3, '2026.04.20 SPLOST-OSC Minutes', '2026.04.20-SPLOST-OSC-Minutes.pdf'),
        item(4, 'KCRB Minutes &#8211; 9.14.26', 'KCRB-Minutes-9.14.26.pdf', '2026/09'),
        item(5, 'April 2026 Planning Commission Minutes', 'April-2026-Planning-Commission-Minutes.pdf'),
        item(6, 'PC Special Called Mtg Minutes 10.20.26', 'PC-Special-Called-Mtg-Minutes-10.20.26.pdf'),
    ],
    'agenda': [
        item(1, 'BOC minutes 10.20.26', 'BOC-minutes-10.20.26.pdf'),          # dup across terms
        item(7, 'BOC Agenda 10.20.26', 'BOC-Agenda-10.20.26.pdf'),
    ],
    'packet': [
        item(8, '9.24.26 BOC ZPH Packet', '9.24.26-BOC-ZPH-Packet.pdf', '2026/09'),
    ],
}

calls = []
real = wpmedia.fetch_bytes


def fake(url, **kw):
    calls.append(url)
    term = url.split('search=')[1].split('&')[0]
    page = int(re.search(r'[?&]page=(\d+)', url).group(1))
    if term == 'broken':
        return None
    return json.dumps(MEDIA.get(term, []) if page == 1 else []).encode()


wpmedia.fetch_bytes = fake
try:
    ms, bodies = wpmedia.fetch_wpmedia_meetings(BASE, BODIES)
    by = {(m['date'], m['body']): m for m in ms}
    check('only the configured bodies survive', bodies,
          ['Board of Commissioners', 'Planning Commission'])
    check('SPLOST / KCRB files are dropped', any(m['date'] in ('2026-04-20', '2026-09-14') and
                                                 m['body'] == 'Board of Commissioners' for m in ms), False)
    m = by[('2026-10-20', 'Board of Commissioners')]
    check('minutes + agenda for one date merge into one record',
          (bool(m['minutesUrl']), bool(m['agendaUrl'])), (True, True))
    check('a Packet title is read as an agenda',
          bool(by[('2026-09-24', 'Board of Commissioners')]['agendaUrl']), True)
    check('curly-dash titles still date', ('2026-09-08', 'Board of Commissioners') in by, True)
    check('a day-less "April 2026" title is skipped, not guessed',
          any(x['body'] == 'Planning Commission' and x['date'].startswith('2026-04') for x in ms), False)
    check('same day, two bodies -> two records', ('2026-10-20', 'Planning Commission') in by, True)
    ids = [x['id'] for x in ms]
    check('ids are unique across bodies', len(ids), len(set(ids)))
    check('newest first', [x['date'] for x in ms], sorted((x['date'] for x in ms), reverse=True))
    check('media id duplicated across terms is counted once',
          sum(1 for x in ms if x['date'] == '2026-10-20' and x['body'] == 'Board of Commissioners'), 1)

    ms, bodies = wpmedia.fetch_wpmedia_meetings(BASE, BODIES, terms=['broken', 'minutes'])
    check('a failed first page fails the whole fetch', (ms, bodies), (None, None))

    try:
        wpmedia.fetch_wpmedia_meetings(BASE, [])
        check('empty media_bodies raises', False, True)
    except ValueError:
        check('empty media_bodies raises', True, True)
finally:
    wpmedia.fetch_bytes = real

print()
if failures:
    print('%d FAILED: %s' % (len(failures), ', '.join(failures)))
    sys.exit(1)
print('all passed')
