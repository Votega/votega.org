#!/usr/bin/env python3
"""Derive the 2026 General Assembly projection from the published results.

WHY THIS EXISTS. The projection shipped as a 236-member array pasted into
_includes/projected-majority-2026.html, with the seat counts, the flip counts
and the list of close races typed into the post's prose beside it. Counting did
not stop when the post went up: on November 7, House district 154 crossed from
Harry James (D) by 59 votes to Gerald E. Greene (R) by 261 — a Republican hold
where the post had counted a flip — and every one of those figures was wrong at
once. The chart said 93-87, the table said 93-87, the bullet said a two-seat
majority, and nothing in the page knew the number had moved.

So the numbers that are MECHANICAL come from here, and are regenerated whenever
results are published. What a district's leader is, which party that is, whether
it differs from the sitting member, how many seats that makes, and which races
are inside two points are all arithmetic on one file; none of them is a
judgement anyone should be retyping at midnight.

WHAT IS DELIBERATELY NOT HERE. The post's framing, its explanation of the
majority line, and its record of what changed since publication are editorial
and stay written by hand. A post is a dated piece of writing, not a dashboard:
this script keeps its facts honest, it does not keep its argument current.

Inputs:
  _data/election_results/<key>.json   the published counts
  assets/data/ga-members.json         the sitting roster, for "flipped"
  _data/ga_unopposed_seats.json       seats with no major-party opponent
  _data/results_updated.json          when those counts were built

Output:
  _data/projected_majority_2026.json

Usage:
  python scripts/build_projected_majority.py [--check]

  --check exits 3 if the output on disk is not what this run would write,
  without touching it, for CI and for a quick "is the post stale?".
"""

import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS_KEY = 'ga-general-2026-results'
RESULTS = os.path.join(ROOT, '_data', 'election_results', RESULTS_KEY + '.json')
ROSTER = os.path.join(ROOT, 'assets', 'data', 'ga-members.json')
UNOPPOSED = os.path.join(ROOT, '_data', 'ga_unopposed_seats.json')
STAMP = os.path.join(ROOT, '_data', 'results_updated.json')
OUT = os.path.join(ROOT, '_data', 'projected_majority_2026.json')

SECTION_CHAMBER = {'state-house': 'House of Representatives', 'state-senate': 'Senate'}
MAJORITY = {'House of Representatives': 91, 'Senate': 29}
SEATS = {'House of Representatives': 180, 'Senate': 56}
# A seat decided by less than this is one the canvass could still move, and the
# post names them. Two points is the figure the post has always used.
NARROW_POINTS = 2.0

PARTY_FROM_SUFFIX = {'Dem': 'Democratic', 'Rep': 'Republican', 'Ind': 'Independent'}
PARTY_FROM_CONTEST = {'dem': 'Democratic', 'rep': 'Republican'}
SUFFIX_RE = re.compile(r'\s*\((Dem|Rep|Ind)\w*\)\s*$')


def _term_rank(member):
    """Sort key for "who holds this seat now": the later term start wins.

    `termStart` is an ISO date where the roster has one and null where it does
    not, so the year is the fallback. A record with neither sorts oldest, which
    is the safe side: it loses to any record that states when its term began.
    """
    start = member.get('termStart') or ''
    year = member.get('termStartYear') or 0
    return (str(start), int(year))


def normalize_name(name):
    """Compare people, not spellings: the results carry `William J. "Bill" Yearta`
    where the roster says `Bill Yearta`. Quoted nicknames, punctuation and case all
    differ between the two files for the same person."""
    bare = re.sub(r'["“”]', '', name or '')
    return re.sub(r'[^a-z0-9]', '', bare.lower())


def leader_of(race):
    """The leading candidate across a district's contests, with their party."""
    best = None
    for contest in race.get('contests') or []:
        for cand in contest.get('candidates') or []:
            match = SUFFIX_RE.search(cand['name'])
            party = (PARTY_FROM_SUFFIX[match.group(1)] if match
                     else PARTY_FROM_CONTEST.get(contest.get('party')))
            entry = {
                'name': SUFFIX_RE.sub('', cand['name']).strip(),
                'party': party,
                'votes': cand.get('votes') or 0,
                'total': contest.get('totalVotes') or 0,
                'candidates': sorted((c.get('votes') or 0) for c in contest['candidates']),
            }
            if best is None or entry['votes'] > best['votes']:
                best = entry
    return best


def district_of(office):
    match = re.search(r'(\d+)', office or '')
    return int(match.group(1)) if match else None


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def build():
    results = load_json(RESULTS)
    roster = load_json(ROSTER).get('members') or []
    unopposed_doc = load_json(UNOPPOSED)
    stamp = load_json(STAMP).get(RESULTS_KEY) or {}

    # ONE SEAT, SEVERAL RECORDS. The roster holds 247 records for 236 seats:
    # eleven districts carry both the sitting member and the predecessor they
    # replaced mid-term. House district 121 has Eric Gisler (D), termStart
    # 2026-01-08, beside Marcus Wiedower (R), who took the seat in 2019 — so
    # whichever record a loop happens to land on decides whether the district
    # counts as Democratic-held, and therefore whether this year's Republican
    # win there is a FLIP or a hold. Taking them in file order silently made it
    # a hold and lost a flip from the count.
    #
    # The most recent term start wins, and anything ambiguous is announced
    # rather than resolved quietly: a seat whose holder cannot be determined is
    # a wrong flip count, which is the number the post leads with.
    sitting = {}
    for member in roster:
        chamber = member.get('chamber')
        district = member.get('district')
        if chamber not in MAJORITY or district is None:
            continue
        key = (chamber, int(district))
        held = sitting.get(key)
        if held is None:
            sitting[key] = member
            continue
        if _term_rank(member) > _term_rank(held):
            sitting[key] = member
            loser, winner = held, member
        else:
            loser, winner = member, held
        print(f"  NOTE: {chamber} district {district} has two roster records "
              f"({winner.get('name')} and {loser.get('name')}); taking "
              f"{winner.get('name')} ({winner.get('party')}) as the sitting member "
              f"on term start {winner.get('termStart') or winner.get('termStartYear')}")

    members, narrow = [], []
    for section in results:
        chamber = SECTION_CHAMBER.get(section.get('id'))
        if not chamber:
            continue
        for race in section.get('races') or []:
            district = district_of(race.get('office'))
            lead = leader_of(race)
            if district is None or lead is None or not lead['party']:
                continue
            incumbent = sitting.get((chamber, district))
            held = incumbent.get('party') if incumbent else None
            flip = None
            if held and held != lead['party']:
                flip = f"{held[0]}→{lead['party'][0]}"
            # The id is the sitting member's, and ONLY when the projection is that
            # same person. The hand-built array carried it regardless, so a flipped
            # seat pointed at the member who had just lost it.
            same = incumbent and normalize_name(incumbent.get('name')) == normalize_name(lead['name'])
            members.append(OrderedDict([
                ('id', incumbent.get('id') if same else None),
                ('name', lead['name']),
                ('district', district),
                ('chamber', chamber),
                ('party', lead['party']),
                ('status', None),
                ('flip', flip),
            ]))
            votes = lead['candidates']
            if len(votes) >= 2 and lead['total']:
                margin = votes[-1] - votes[-2]
                points = 100.0 * margin / lead['total']
                if points < NARROW_POINTS:
                    # Pre-formatted thousands separators: Liquid has no filter
                    # for them, and "23984 cast" in a sentence reads as a typo.
                    narrow.append(OrderedDict([
                        ('chamber', chamber), ('district', district),
                        ('leader', lead['name']), ('party', lead['party']),
                        ('margin', margin), ('marginDisplay', f'{margin:,}'),
                        ('total', lead['total']), ('totalDisplay', f"{lead['total']:,}"),
                        ('points', round(points, 2)),
                    ]))

    members.sort(key=lambda m: (m['chamber'], m['district']))
    narrow.sort(key=lambda n: n['points'])

    chambers = OrderedDict()
    for chamber in ('House of Representatives', 'Senate'):
        seats = [m for m in members if m['chamber'] == chamber]
        dem = sum(1 for m in seats if m['party'] == 'Democratic')
        rep = sum(1 for m in seats if m['party'] == 'Republican')
        flips = OrderedDict()
        for m in seats:
            if m['flip']:
                flips[m['flip']] = flips.get(m['flip'], 0) + 1
        line = MAJORITY[chamber]
        # The chamber as it stands today, from the same deduplicated roster the
        # flip comparison uses — so the "current" column of the post's table
        # cannot drift away from the column beside it, and a mid-term change of
        # seat shows up in both at once.
        held = [m for (ch, _d), m in sitting.items() if ch == chamber]
        held_dem = sum(1 for m in held if m.get('party') == 'Democratic')
        held_rep = sum(1 for m in held if m.get('party') == 'Republican')
        chambers[chamber] = OrderedDict([
            ('seats', SEATS[chamber]), ('projected', len(seats)),
            ('currentDemocratic', held_dem), ('currentRepublican', held_rep),
            ('currentOther', len(held) - held_dem - held_rep),
            ('democratic', dem), ('republican', rep),
            ('other', len(seats) - dem - rep),
            ('majority', line),
            ('democraticMargin', dem - line), ('republicanMargin', rep - line),
            ('flips', flips),
            ('flipsToDemocratic', flips.get('R→D', 0)),
            ('flipsToRepublican', flips.get('D→R', 0)),
            ('netDemocraticGain', flips.get('R→D', 0) - flips.get('D→R', 0)),
        ])

    unopposed_map = {'house': {}, 'senate': {}}
    for seat in unopposed_doc.get('seats') or []:
        if seat.get('chamber') in unopposed_map and seat.get('district') is not None:
            unopposed_map[seat['chamber']][str(seat['district'])] = seat.get('party')

    return OrderedDict([
        ('metadata', OrderedDict([
            ('generatedAt', datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
            ('source', 'scripts/build_projected_majority.py, from the published results, '
                       'the sitting roster and the unopposed-seat list'),
            ('resultsKey', RESULTS_KEY),
            ('resultsEpoch', stamp.get('epoch')),
            ('resultsIso', stamp.get('iso')),
            ('narrowPoints', int(NARROW_POINTS) if float(NARROW_POINTS).is_integer()
                              else NARROW_POINTS),
        ])),
        ('chambers', chambers),
        ('narrow', narrow),
        ('unopposedSeats', unopposed_map),
        ('members', members),
    ])


def main(argv):
    doc = build()
    if '--check' in argv:
        if not os.path.exists(OUT):
            print(f'STALE: {OUT} does not exist')
            return 3
        current = load_json(OUT)
        a = {k: v for k, v in doc.items() if k != 'metadata'}
        b = {k: v for k, v in current.items() if k != 'metadata'}
        if a != b:
            print('STALE: the projection on disk does not match the published results. '
                  'Run: python scripts/build_projected_majority.py')
            return 3
        print('Projection is current.')
        return 0
    write_json_atomic(OUT, doc, indent=2)
    for chamber, c in doc['chambers'].items():
        print(f"  {chamber}: now {c['currentDemocratic']} D / {c['currentRepublican']} R "
              f"-> {c['democratic']} D / {c['republican']} R "
              f"(line {c['majority']}, D {c['democraticMargin']:+d}) "
              f"flips R->D {c['flipsToDemocratic']}, D->R {c['flipsToRepublican']}")
    print(f"  {len(doc['narrow'])} seat(s) inside {NARROW_POINTS} points")
    print(f'Wrote: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
