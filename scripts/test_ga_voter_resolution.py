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

from lib.ga_voters import (LEGACY_PERSON_ID_MAP, MemberIndex,  # noqa: E402
                           chamber_from_motion, event_chamber,
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

# An 'agree to' motion names whose work is being ACCEPTED, so the chamber casting the
# vote is the other one. Reading it at face value put 136 of the session's 270 such
# roll calls in the wrong chamber and, because the old test was case-sensitive, left
# the 134 upper-case Senate motions with no chamber at all.
print("")
print("=== chamber_from_motion: the 'agree to' family is inverted ===")
AGREE_CASES = [
    ('AGREE TO HOUSE SUBSTITUTE', SENATE),
    ('AGREE TO HOUSE SUBSTITUTE AS AMENDED', SENATE),
    ('AGREE TO HOUSE AMENDMENT TO SENATE SUBSTITUTE', SENATE),
    ('AGREE TO HOUSE AMENDMENT TO SENATE AMENDMENT TO HOUSE SUBSTITUTE', SENATE),
    ('Agree to Senate Substitute', HOUSE),
    ('Agree to Senate Sub as Am', HOUSE),
    ('Agree to Senate Amendment', HOUSE),
    ('Agree to Senate Amend to House Sub', HOUSE),
    # The House amends the Senate's substitute and agrees to it in one motion: still
    # a House vote, even though 'House' appears last.
    ('Agree to Senate Sub as Amended by House', HOUSE),
    ('Agree to Senate Amend to HAm to SSub', HOUSE),
]
for motion, want in AGREE_CASES:
    check('%-62s -> %s' % ('"' + motion + '"', want), chamber_from_motion(motion), want)

# Motions that name no chamber must stay unknown rather than guess: callers read '' as
# 'do not filter', which keeps a real vote in the member's own-chamber stats.
for motion in ('PASSAGE', 'PASSAGE BY SUBSTITUTE', 'Local Calendar',
               'LOCAL CONSENT CALENDAR', 'ADOPT', 'ADOPT CONFERENCE COMMITTEE REPORT'):
    check('%-40s -> unknown' % ('"' + motion + '"'), chamber_from_motion(motion), '')

print("")
print("=== curated key votes: picking the operative final vote ===")
import generate_curated_ga_bills as gen  # noqa: E402
from lib.votes_schema import VOTE_CODES  # noqa: E402

# A chamber can hold several passage roll calls on one bill on one day (89 such groups
# in 2025-26), and in 5 of them one passed while another failed -- so picking by dict or
# fetch order could show a failed attempt as the outcome. rollNumber, the chamber's own
# sequence, settles it; it cannot be derived downstream, which is why it is stored.
SAME_DAY = [
    {"rollNumber": 884, "date": "2025-03-31", "time": "10:12 PM",
     "motionText": "AGREE TO HOUSE SUBSTITUTE AS AMENDED", "result": "fail"},
    {"rollNumber": 883, "date": "2025-03-31", "time": "9:58 PM",
     "motionText": "AGREE TO HOUSE SUBSTITUTE", "result": "pass"},
]
check("highest rollNumber wins, whichever order they arrive in",
      gen.select_final_vote(SAME_DAY)["rollNumber"], 884)
check("  ...and reversing the input does not change it",
      gen.select_final_vote(list(reversed(SAME_DAY)))["rollNumber"], 884)

# Without a rollNumber (records predating the field) fall back to date, then clock
# time, then a vote that passed over one that did not -- never input order.
NO_NUMBER = [
    {"date": "2025-03-31", "time": "9:58 PM", "result": "pass"},
    {"date": "2025-03-31", "time": "10:12 PM", "result": "fail"},
]
check("later clock time wins when rollNumber is absent",
      gen.select_final_vote(NO_NUMBER)["time"], "10:12 PM")
check("a later date beats an earlier one", gen.select_final_vote([
    {"date": "2026-03-31", "result": "pass"}, {"date": "2025-03-31", "result": "pass"}
])["date"], "2026-03-31")
check("with nothing else to go on, a vote that passed beats one that did not",
      gen.select_final_vote([{"result": "fail"}, {"result": "pass"}])["result"], "pass")
check("no candidates -> None", gen.select_final_vote([]), None)
check("12:05 AM sorts before 1:00 PM", gen._minutes("12:05 AM") < gen._minutes("1:00 PM"), True)
check("an unparseable clock does not crash", gen._minutes("noon"), 0)

print("")
print("=== curated key votes: option vocabulary and party tally ===")
# Every vote string the producers can emit must map, or a real position would silently
# become "other" by falling through a .get() default.
for option in VOTE_CODES:
    check("%-12s maps to a published option" % option, option in gen.OPTION, True)

PARTIES = {"p/r1": "Republican", "p/r2": "Republican", "p/d1": "Democratic",
           "p/i1": "Independent", "p/unknown": None}
TALLY = gen.build_party_tally(
    {"p/r1": "yes", "p/r2": "no", "p/d1": "yes", "p/i1": "other", "p/unknown": "yes"},
    PARTIES)
check("R yea", TALLY["Republican"]["yea"], 1)
check("R nay", TALLY["Republican"]["nay"], 1)
check("D yea", TALLY["Democratic"]["yea"], 1)
check("abstain/not-voting lands in other", TALLY["Independent"]["other"], 1)
# A member whose party we do not know is counted in no bucket, so the bars never
# imply a party voted a way it did not.
check("unknown party is not counted",
      sum(b["yea"] + b["nay"] + b["other"] for b in TALLY.values()), 4)

print('\n=== assign_remaining_by_surname: elimination against the roster ===')
from lib.ga_voters import assign_remaining_by_surname, surname_key  # noqa: E402

SUR = FakeIndex([
    {'id': 'h/jones-a', 'name': 'Jan Jones', 'chamber': HOUSE, 'party': 'Republican'},
    {'id': 'h/jones-b', 'name': 'Todd Jones', 'chamber': HOUSE, 'party': 'Republican'},
    {'id': 'h/jones-c', 'name': 'Sheila Jones', 'chamber': HOUSE, 'party': 'Democratic'},
    {'id': 'h/solo', 'name': 'Teri Anulewicz', 'chamber': HOUSE, 'party': 'Democratic'},
    {'id': 's/jones-d', 'name': 'Emanuel Jones', 'chamber': SENATE, 'party': 'Democratic'},
])

check('surname_key strips suffixes', surname_key('Floyd L Griffin Jr'), 'griffin')
check('surname_key of a bare surname', surname_key('JONES'), 'jones')

# Unique surname, nothing else needed.
a, u = assign_remaining_by_surname([(0, 'ANULEWICZ', 'yes')], set(), HOUSE, SUR)
check('unique surname resolves', a, {0: 'h/solo'})

# All three Joneses unresolved and all voted the same way -> determinate as a set.
rows = [(0, 'JONES', 'no'), (1, 'JONES', 'no'), (2, 'JONES', 'no')]
a, u = assign_remaining_by_surname(rows, set(), HOUSE, SUR)
check('3 rows / 3 members / same option -> all assigned', len(a), 3)
check('  assigned to the three distinct Joneses', sorted(a.values()),
      ['h/jones-a', 'h/jones-b', 'h/jones-c'])

# Split vote within the group: who voted which way is unknowable. Refuse.
rows = [(0, 'JONES', 'yes'), (1, 'JONES', 'no'), (2, 'JONES', 'no')]
a, u = assign_remaining_by_surname(rows, set(), HOUSE, SUR)
check('3 rows / 3 members / SPLIT option -> refuses', a, {})
check('  and reports all three unresolved', sorted(u), [0, 1, 2])

# Count mismatch: 2 rows but 3 candidates -> someone is unaccounted for. Refuse.
rows = [(0, 'JONES', 'no'), (1, 'JONES', 'no')]
a, u = assign_remaining_by_surname(rows, set(), HOUSE, SUR)
check('2 rows / 3 members -> refuses', a, {})

# ...unless the third is already resolved by id, which restores the balance.
a, u = assign_remaining_by_surname(rows, {'h/jones-c'}, HOUSE, SUR)
check('2 rows / 3 members, 1 already resolved -> assigns the other 2', len(a), 2)
check('  never reassigns the already-resolved member', 'h/jones-c' in a.values(), False)

# Chamber scoping: the Senate Jones is not a candidate for a House row.
rows = [(0, 'JONES', 'no'), (1, 'JONES', 'no'), (2, 'JONES', 'no')]
a, u = assign_remaining_by_surname(rows, set(), HOUSE, SUR)
check('Senate member never fills a House row', 's/jones-d' in a.values(), False)

# A surname nobody in the chamber has.
a, u = assign_remaining_by_surname([(0, 'NOBODY', 'yes')], set(), HOUSE, SUR)
check('unknown surname -> unresolved', (a, u), ({}, [0]))

# Departed members (the 2023-24 bills): rows outnumber the sitting roster.
rows = [(0, 'ANULEWICZ', 'yes'), (1, 'LOTT', 'yes'), (2, 'BEVERLY', 'no')]
a, u = assign_remaining_by_surname(rows, set(), HOUSE, SUR)
check('former members are not invented into the roster', sorted(a.values()), ['h/solo'])
check('  the rest stay unresolved', sorted(u), [1, 2])

check('no chamber -> refuses everything',
      assign_remaining_by_surname([(0, 'JONES', 'no')], set(), None, SUR), ({}, [0]))

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
sys.exit(1 if FAIL else 0)
