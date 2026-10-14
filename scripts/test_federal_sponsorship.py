#!/usr/bin/env python3
"""Invariants of the federal sponsorship fetch + slice writer (lib/federal_sponsorship.py).

generate_current_members_data.py used to call
``/member/{bioguide}/sponsored-legislation?limit=20`` once and filter the 20 rows
it got to the current Congress. These tests pin the three things that replaced it,
none of which can be exercised against the live API in a session without a
CONGRESS_API_KEY — so fetch_member_legislation() takes its fetcher as an argument
and the fake below reproduces the API's real shape:

  * the walk is complete (a career list spanning several Congresses pages fully),
  * a failed page discards the whole list instead of publishing a short one, and
  * the order the rows end up in does not depend on the order they paged in.

Run: python scripts/test_federal_sponsorship.py        (no network, no repo writes)
"""
import json
import os
import random
import sys
import tempfile
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.federal_sponsorship import (fetch_member_legislation, most_recent,
                                     write_sponsorship_artifacts)

CONGRESS = 119
failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def make_corpus(n_current, n_old, interleave=True):
    """n_current current-Congress rows + n_old previous-Congress rows.

    Interleaved by default, because that is the behaviour that broke the old code:
    these endpoints are not ordered newest-Congress-first, so *which* 20 rows
    survived the filter was effectively arbitrary. Measured on the committed
    roster, Sen. Warnock surfaced 3 bills and Sen. Ossoff 14 from the same 20-row
    page — and Warnock has the larger career record of the two.
    """
    rows = []
    cur, old = n_current, n_old
    for i in range(n_current + n_old):
        if ((i % 2 == 0) if interleave else (i < n_current)) and cur > 0:
            cur -= 1
            congress = CONGRESS
        elif old > 0:
            old -= 1
            congress = CONGRESS - 1
        else:
            cur -= 1
            congress = CONGRESS
        rows.append({
            'congress': congress, 'type': 'HR', 'number': 1000 + i,
            'title': 'A bill number %d' % i,
            'introducedDate': '2025-%02d-%02d' % ((i % 12) + 1, (i % 28) + 1),
            'latestAction': {'actionDate': '2025-06-01',
                             'text': 'Referred to the Subcommittee on Health.'},
            'policyArea': {'name': 'Health' if i % 3 else 'Taxation'},
        })
    return rows


def fake_api(corpus, envelope, fail_on_page=None, omit_next_on_full_page=False):
    """Stand-in for fetch_url(): honours limit/offset, counts pages, can fail one."""
    state = {'pages': 0}

    def fetch(url):
        state['pages'] += 1
        if fail_on_page and state['pages'] == fail_on_page:
            return None          # what lib.http returns once its retries are spent
        query = parse_qs(urlparse(url).query)
        limit = int(query['limit'][0])
        offset = int(query['offset'][0])
        page = corpus[offset:offset + limit]
        nxt = ''
        if offset + limit < len(corpus) and not omit_next_on_full_page:
            # Rebuilt rather than string-substituted: 'offset=250' would also
            # match 'limit=250' in the same query string.
            nxt = '%s?limit=%d&offset=%d&format=json' % (
                url.split('?')[0], limit, offset + limit)
        return {envelope: page, 'pagination': {'count': len(corpus), 'next': nxt}}

    return fetch, state


print("1,000 career records (600 in the current Congress), interleaved:")
corpus = make_corpus(600, 400)
fetch, state = fake_api(corpus, 'sponsoredLegislation')
rows = fetch_member_legislation(fetch, 'A000001', 'sponsored', CONGRESS, delay=0)
check('complete current-Congress record', len(rows), 600)
check('4 pages at limit=250, no confirming 5th (pagination.count stops the walk)',
      state['pages'], 4)
print("  note the old single limit=20 page would have yielded %d of the 600"
      % len([r for r in corpus[:20] if r['congress'] == CONGRESS]))

print("A page that fails mid-walk:")
fetch, _ = fake_api(corpus, 'sponsoredLegislation', fail_on_page=3)
check('discards the whole list rather than publishing a truncated one',
      fetch_member_legislation(fetch, 'A000001', 'sponsored', CONGRESS, delay=0), None)

print("A record that is an exact multiple of the page size, with `next` omitted:")
corpus2 = make_corpus(500, 0, interleave=False)
fetch, state = fake_api(corpus2, 'cosponsoredLegislation', omit_next_on_full_page=True)
rows2 = fetch_member_legislation(fetch, 'A000001', 'cosponsored', CONGRESS, delay=0)
check('offset fallback recovers the final page', len(rows2), 500)
check('and stops at pagination.count instead of fetching past the end',
      state['pages'], 2)

print("Rows the panel could not render:")
fetch, _ = fake_api([{'congress': CONGRESS, 'type': 'HR', 'number': 1, 'title': ''},
                     {'congress': CONGRESS, 'type': '', 'number': 2, 'title': 'x'},
                     {'congress': CONGRESS, 'type': 'S', 'number': 3, 'title': 'Keep me'}],
                    'sponsoredLegislation')
kept = fetch_member_legislation(fetch, 'A000001', 'sponsored', CONGRESS, delay=0)
check('dropped, not published blank', [k['number'] for k in kept], ['3'])
check('absent optional field is None, never ""', kept[0]['introducedDate'], None)
check('billUrl derived from congress+type+number', kept[0]['billUrl'],
      'https://www.congress.gov/bill/119th-congress/senate-bill/3')

print("Ordering is a property of the data, not of the paging:")
shuffled = rows[:]
random.Random(1).shuffle(shuffled)
check('most_recent() stable under reordering',
      [b['number'] for b in most_recent(rows, 20)],
      [b['number'] for b in most_recent(shuffled, 20)])

print("Index + slice artifacts:")
with tempfile.TemporaryDirectory() as tmp:
    slices = os.path.join(tmp, 'federal-sponsorship')
    os.makedirs(slices)
    with open(os.path.join(slices, 'Z999999.json'), 'w') as fh:
        fh.write('{}')      # a member who has left the delegation
    stats = write_sponsorship_artifacts(tmp, CONGRESS, {
        'A000001': {'name': 'Test, One', 'primary': rows[:30], 'cosponsored': rows2},
        'B000002': {'name': 'Test, Two', 'primary': [], 'cosponsored': []},
    }, generated_at='2026-10-14T00:00:00+00:00', log=lambda *a: None)
    check('stale slice cleared (no dangling live-looking record)',
          os.path.exists(os.path.join(slices, 'Z999999.json')), False)
    index = json.load(open(os.path.join(tmp, 'federal-sponsorship-index.json')))
    check('index count map drives tab visibility', index['members'],
          {'A000001': [30, 500], 'B000002': [0, 0]})
    check('index stamps its own congress', index['metadata']['congress'], CONGRESS)
    sl = json.load(open(os.path.join(slices, 'A000001.json')))
    check('slice row width matches the R_* constants in the entity include',
          len(sl['primary'][0]), 7)
    check('recurring action text interned once per slice', len(sl['actions']), 1)
    check('slice rows are newest-introduced first',
          sl['primary'][0][3] >= sl['primary'][-1][3], True)
    print("  %d bytes/row across the heaviest slice (%d rows, %.0f KB)"
          % (stats['maxSliceBytes'] / len(rows2), len(rows2),
             stats['maxSliceBytes'] / 1024))

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    sys.exit(1)
print("All federal sponsorship invariants hold.")
