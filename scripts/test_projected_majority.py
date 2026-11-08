#!/usr/bin/env python3
"""Pin the projection the General Assembly post publishes.

The post's seat counts, flip counts and close-race list used to be typed by
hand beside a 236-member array pasted into the include. When House district 154
crossed from Harry James (D) by 59 votes to Gerald E. Greene (R) by 261 on
November 7, every one of those figures was wrong at once and nothing noticed.
scripts/build_projected_majority.py derives them instead; this pins the parts
that would go wrong quietly.

THE BUG THIS FILE EXISTS FOR. The roster carries 247 records for 236 seats:
eleven districts hold both the sitting member and the predecessor they replaced
mid-term. House district 121 has Eric Gisler (D), who took the seat in January
2026, beside Marcus Wiedower (R), who held it from 2019. Whichever record a
loop lands on decides whether a Republican win there is a FLIP or a hold — and
taking them in file order quietly made it a hold, losing a flip from the number
the post leads with. The later term start wins, and a duplicate is announced
rather than resolved in silence.

Usage:
  python scripts/test_projected_majority.py

Exits 0 on success, 1 on any failure.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_projected_majority as bpm  # noqa: E402

FAILURES = []


def check(label, condition, detail=''):
    if condition:
        print(f'  PASS {label}')
    else:
        print(f'  FAIL {label}{" — " + detail if detail else ""}')
        FAILURES.append(label)


print('Who holds a seat when the roster lists two people for it')
older = {'name': 'Marcus Wiedower', 'party': 'Republican', 'termStart': None, 'termStartYear': 2019}
newer = {'name': 'Eric Gisler', 'party': 'Democratic', 'termStart': '2026-01-08', 'termStartYear': 2026}
check('a dated term start beats an undated one',
      bpm._term_rank(newer) > bpm._term_rank(older))
check('a later year beats an earlier one',
      bpm._term_rank({'termStart': None, 'termStartYear': 2026}) >
      bpm._term_rank({'termStart': None, 'termStartYear': 2019}))
check('a record with neither sorts oldest, so it never displaces a dated one',
      bpm._term_rank({}) < bpm._term_rank(older))

print('Names are compared as people, not spellings')
check('a quoted nickname does not make a new person',
      bpm.normalize_name('William J. "Bill" Yearta') == bpm.normalize_name('William J. Bill Yearta'))
check('case and punctuation do not either',
      bpm.normalize_name('Gerald E. Greene') == bpm.normalize_name('gerald e greene'))
check('different people still differ',
      bpm.normalize_name('Harry James') != bpm.normalize_name('Gerald E. Greene'))

print('The leader of a district, and their party')
race = {'office': 'District 154', 'contests': [{'party': 'np', 'totalVotes': 20125, 'candidates': [
    {'name': 'Gerald E. Greene (Rep)', 'votes': 10193},
    {'name': 'Harry James (Dem)', 'votes': 9932}]}]}
lead = bpm.leader_of(race)
check('the leader is the candidate with the most votes',
      lead['name'] == 'Gerald E. Greene' and lead['party'] == 'Republican',
      f"{lead['name']} / {lead['party']}")
check('the party suffix is read off the ballot name, not the contest',
      lead['party'] == 'Republican')
single = bpm.leader_of({'office': 'District 7', 'contests': [
    {'party': 'rep', 'totalVotes': 100, 'candidates': [{'name': 'Solo', 'votes': 100}]}]})
check('an unopposed candidate takes the contest party', single['party'] == 'Republican')

print('The published projection matches the published results')
doc = bpm.build()
check('every seat is accounted for', len(doc['members']) == 236, str(len(doc['members'])))
for chamber, expect_seats in (('House of Representatives', 180), ('Senate', 56)):
    c = doc['chambers'][chamber]
    total = c['democratic'] + c['republican'] + c['other']
    check(f'{chamber}: the parties sum to the chamber',
          total == expect_seats, f'{total} of {expect_seats}')
    check(f'{chamber}: the margin is the count against the line',
          c['democraticMargin'] == c['democratic'] - c['majority'])
    check(f'{chamber}: the net gain is the two flip directions',
          c['netDemocraticGain'] == c['flipsToDemocratic'] - c['flipsToRepublican'])

house = doc['chambers']['House of Representatives']
check('House district 121 counts as a Democratic-held seat flipping Republican, '
      'not a Republican hold',
      any(m['district'] == 121 and m['chamber'] == 'House of Representatives'
          and m['flip'] == 'D→R' for m in doc['members']),
      str([m for m in doc['members']
           if m['district'] == 121 and m['chamber'] == 'House of Representatives']))
check('House district 154 is a Republican hold, not a flip',
      any(m['district'] == 154 and m['chamber'] == 'House of Representatives'
          and m['party'] == 'Republican' and m['flip'] is None for m in doc['members']))
check('the flip counts are not zero (the roster join still works)',
      house['flipsToDemocratic'] > 0 and house['flipsToRepublican'] > 0,
      f"R->D {house['flipsToDemocratic']}, D->R {house['flipsToRepublican']}")

print('The close-race list')
check('it is sorted closest first',
      doc['narrow'] == sorted(doc['narrow'], key=lambda n: n['points']))
check('every entry is inside the threshold',
      all(n['points'] < doc['metadata']['narrowPoints'] for n in doc['narrow']))
check('the threshold prints as a whole number, not 2.0',
      isinstance(doc['metadata']['narrowPoints'], int), repr(doc['metadata']['narrowPoints']))
check('margins carry thousands separators for Liquid, which has no filter for them',
      all(n['marginDisplay'] == f"{n['margin']:,}" for n in doc['narrow']))

print('A projected winner who is not the sitting member carries no member id')
for m in doc['members']:
    if m['flip'] and m['id'] is not None:
        check('a flipped seat does not point at the member who just lost it', False,
              f"{m['chamber']} {m['district']} -> {m['id']}")
        break
else:
    check('a flipped seat does not point at the member who just lost it', True)

print('The committed file is current')
check('_data/projected_majority_2026.json matches the results on disk',
      bpm.main(['--check']) == 0)

if FAILURES:
    print(f'\n{len(FAILURES)} check(s) failed: {", ".join(FAILURES)}')
    sys.exit(1)
print('\nAll checks passed.')
