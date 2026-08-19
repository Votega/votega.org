#!/usr/bin/env python3
"""Tests for lib.ga_voters.resolve_voter and the curated vote-record builder.

These guard the join that CODEBASE-REVIEW-2026-08-18.md finding 1.5 describes:
21 deprecated OCD person ids left 38 of 232 sitting legislators with no key
votes, because the name fallback was gated on a *missing* id and these ids were
present — just stale.

The bar here is asymmetric on purpose. Dropping a vote shows a legislator as
having no record; attributing one to the wrong person publishes a false claim
about how they voted. Every ambiguous case must therefore resolve to nothing,
not to a guess.

Usage:
  python scripts/test_ga_voter_resolution.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ga_voters import (LEGACY_PERSON_ID_MAP, MemberIndex, event_chamber,  # noqa: E402
                           new_stats, normalize_voter_name, resolve_voter)

HOUSE = 'House of Representatives'
SENATE = 'Senate'

PASS = []
FAIL = []


def check(label, got, want):
    (PASS if got == want else FAIL).append(label)
    flag = 'PASS' if got == want else 'FAIL'
    print(f'  {flag}  {label}')
    if got != want:
        print(f'          got={got!r}  want={want!r}')


class FakeIndex(MemberIndex):
    """MemberIndex built from literals instead of a file."""

    def __init__(self, members):
        self.by_id, self.chambers, self.parties, self.by_name = {}, {}, {}, {}
        for m in members:
            mid = m['id']
            self.by_id[mid] = m
            self.chambers[mid] = m.get('chamber')
            self.parties[mid] = m.get('party')
            key = (m['chamber'], normalize_voter_name(m['name']))
            self.by_name[key] = None if key in self.by_name else mid


IDX = FakeIndex([
    {'id': 'ocd-person/aaa', 'name': 'Jan Jones', 'chamber': HOUSE, 'party': 'Republican'},
    {'id': 'ocd-person/bbb', 'name': 'Todd Jones', 'chamber': HOUSE, 'party': 'Republican'},
    {'id': 'ocd-person/ccc', 'name': 'Emanuel Jones', 'chamber': SENATE, 'party': 'Democratic'},
    {'id': 'ocd-person/ddd', 'name': 'Park Cannon', 'chamber': HOUSE, 'party': 'Democratic'},
    # Two members sharing a name within one chamber: never attributable.
    {'id': 'ocd-person/eee', 'name': 'Same Name', 'chamber': HOUSE, 'party': 'Republican'},
    {'id': 'ocd-person/fff', 'name': 'Same Name', 'chamber': HOUSE, 'party': 'Democratic'},
])

print('=== resolve_voter ===')

check('known id resolves by id',
      resolve_voter('ocd-person/aaa', 'Jan Jones', HOUSE, IDX), ('ocd-person/aaa', 'id'))

# THE FINDING: id present but stale. Previously skipped the fallback entirely.
check('ghost id + resolvable name -> recovered by name',
      resolve_voter('ocd-person/GHOST', 'Jan Jones', HOUSE, IDX), ('ocd-person/aaa', 'name'))

check('missing id + resolvable name -> recovered by name',
      resolve_voter(None, 'Todd Jones', HOUSE, IDX), ('ocd-person/bbb', 'name'))

check('ghost id + unknown name -> ghost, no attribution',
      resolve_voter('ocd-person/GHOST', 'Nobody Here', HOUSE, IDX), (None, 'ghost'))

check('no id + unknown name -> unresolved',
      resolve_voter(None, 'Nobody Here', HOUSE, IDX), (None, 'unresolved'))

# Chamber scoping: the surname-collision case the whole fallback exists for.
check('name is scoped to chamber (Emanuel Jones is a Senator)',
      resolve_voter('ocd-person/GHOST', 'Emanuel Jones', HOUSE, IDX), (None, 'ghost'))
check('same name, correct chamber -> resolves',
      resolve_voter('ocd-person/GHOST', 'Emanuel Jones', SENATE, IDX), ('ocd-person/ccc', 'name'))

# Ambiguity must never be guessed.
check('name matching two members in a chamber -> refuses',
      resolve_voter('ocd-person/GHOST', 'Same Name', HOUSE, IDX), (None, 'ghost'))
check('ambiguous name with no id -> refuses',
      resolve_voter(None, 'Same Name', HOUSE, IDX), (None, 'unresolved'))

check('no chamber known -> no name fallback',
      resolve_voter('ocd-person/GHOST', 'Jan Jones', None, IDX), (None, 'ghost'))

# Legacy alias
old, new = next(iter(LEGACY_PERSON_ID_MAP.items()))
ALIAS_IDX = FakeIndex([{'id': new, 'name': 'Jon Burns', 'chamber': HOUSE, 'party': 'Republican'}])
check('deprecated id folds into the current one',
      resolve_voter(old, 'Jon Burns', HOUSE, ALIAS_IDX), (new, 'alias'))

# Name-format tolerance
check('"Last, First" form normalizes',
      resolve_voter(None, 'Jones, Jan', HOUSE, IDX), ('ocd-person/aaa', 'name'))
check('title prefix is stripped',
      resolve_voter(None, 'Rep. Jan Jones', HOUSE, IDX), ('ocd-person/aaa', 'name'))

# No member data at all: trust the id rather than discarding everything.
check('empty index falls back to trusting the id',
      resolve_voter('ocd-person/xyz', 'Whoever', HOUSE, FakeIndex([])), ('ocd-person/xyz', 'id'))

print('\n=== event_chamber ===')
check('organization classification wins',
      event_chamber('anything', {'classification': 'upper'}), SENATE)
check('falls back to motion text', event_chamber('House Vote #12', None), HOUSE)
check('unknown -> None', event_chamber('Vote #12', None), None)

print('\n=== build_vote_record: tally is derived from the deduped roster ===')
import generate_curated_ga_bills as gen  # noqa: E402

party_lookup = {m['id']: m['party'] for m in IDX.by_id.values()}

# Same voter listed twice (Open States does this) + one ghost recoverable by name.
event = {
    'motion_text': 'House Vote #99 - 2025-2026 Regular Session',
    'organization': {'classification': 'lower'},
    'votes': [
        {'voter': {'id': 'ocd-person/aaa'}, 'voter_name': 'Jan Jones', 'option': 'yes'},
        {'voter': {'id': 'ocd-person/aaa'}, 'voter_name': 'Jan Jones', 'option': 'yes'},
        {'voter': {'id': 'ocd-person/GHOST'}, 'voter_name': 'Todd Jones', 'option': 'no'},
        {'voter': {'id': 'ocd-person/ddd'}, 'voter_name': 'Park Cannon', 'option': 'no'},
        {'voter': {'id': 'ocd-person/NOPE'}, 'voter_name': 'Unknown Person', 'option': 'yes'},
    ],
}
stats = new_stats()
rec = gen.build_vote_record(event, party_lookup, IDX, stats)

check('duplicate voter collapses in memberVotes', len(rec['memberVotes']), 3)
check('ghost id recovered onto the right member',
      rec['memberVotes'].get('ocd-person/bbb'), 'no')
check('unrecoverable ghost is omitted',
      'ocd-person/NOPE' in rec['memberVotes'], False)

tally_total = sum(b['yea'] + b['nay'] + b['other'] for b in rec['partyTally'].values())
check('partyTally equals the roster, not the row count', tally_total, 3)
check('  R yea', rec['partyTally']['Republican']['yea'], 1)
check('  R nay', rec['partyTally']['Republican']['nay'], 1)
check('  D nay', rec['partyTally']['Democratic']['nay'], 1)
check('stats counted every row', sum(stats.values()), 5)
check('  ghost counted', stats['ghost'], 1)
check('  name fallback counted', stats['name'], 1)

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
sys.exit(1 if FAIL else 0)
