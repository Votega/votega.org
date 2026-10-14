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

import json
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
print("=== legis session table: ids come from the source, never from a guess ===")
from lib.ga_sessions import (LEGIS_SESSIONS, legis_session_id, legis_session_library,  # noqa: E402
                             legis_session_table, regular_session_description)

# The id space is neither contiguous nor ordered by era (1, 6, 7, 11, 13-15, 18, 20-27,
# then 1027+), so every id must come from Session/GetSessions via the committed table --
# 2019-2020 is id 27, which no sequential probe would find.
TABLE = legis_session_table()
check("the committed table loaded", len(TABLE) >= 20, True)
check("2025_26 -> 1033", legis_session_id("2025_26"), 1033)
check("2026_ss -> 1034 (special, explicit)", legis_session_id("2026_ss"), 1034)
check("2023_24 -> 1031", legis_session_id("2023_24"), 1031)
check("2019_20 -> 27, not 1026", legis_session_id("2019_20"), 27)
check("2001_02 -> 1", legis_session_id("2001_02"), 1)
check("library comes along", legis_session_library("2023_24"), "20232024")

# A `YYYY_YY` tag derives a DESCRIPTION, which is then looked up in the table. The
# derivation never invents an id, so an unknown description resolves to nothing.
check("tag -> description", regular_session_description("2013_14"), "2013-2014 Regular Session")
for tag in ("2026_ss", "2023_25", "2023_2024", "garbage", ""):
    check("%-11s derives nothing" % repr(tag), regular_session_description(tag), "")
check("a tag outside the table resolves to None", legis_session_id("1899_00"), None)

# Every regular session in the table must resolve from its bare tag.
_missed = []
for _desc, _row in TABLE.items():
    if "Regular" not in _desc:
        continue
    _y = int(_desc[:4])
    if legis_session_id("%d_%s" % (_y, str(_y + 1)[2:])) != _row["id"]:
        _missed.append(_desc)
check("every regular session resolves from its tag", _missed, [])

# The hardcoded fallback must not contradict the source, or an offline run would
# silently use a different session than a normal one.
_drift = [t for t, v in LEGIS_SESSIONS.items()
          if legis_session_id(t) is not None and v["id"] != legis_session_id(t)]
check("the offline fallback agrees with the table", _drift, [])

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



# ---------------------------------------------------------------------------
# Roster field normalization (lib.ga_roster) — Phase 1 of the roster SOAP
# migration. legis.ga.gov's `Address1` is free text: it spells the one building
# five ways, separates some lines with semicolons, and leaves a trailing hyphen
# on a ZIP. These are the real values, taken from the 251-member listing.
# ---------------------------------------------------------------------------
print('\nlib.ga_roster.normalize_address')

from lib.ga_roster import display_committee, normalize_address  # noqa: E402

CLOB = 'Coverdell Legislative Office Building'

check('canonical form passes through unchanged',
      normalize_address('511-A ' + CLOB, 'Atlanta', 'GA', '30334'),
      f'511-A {CLOB}, Atlanta, GA 30334')

# The five spellings of one building, all seen in production.
for raw, label in [('320-B CLOB', 'bare acronym'),
                   ('409-E Coverdell Legislative Office Bldg', 'Bldg'),
                   ('612-A Coverdell Legislative Office Bldg.', 'Bldg.'),
                   ('301 Coverdell Legislative Bldg.', 'no "Office"')]:
    room = raw.split(' ', 1)[0]
    check(f'building spelling normalized ({label})',
          normalize_address(raw, 'Atlanta', 'GA', '30334'),
          f'{room} {CLOB}, Atlanta, GA 30334')

check('the Capitol is left alone — it is not the same building',
      normalize_address('HM-1 State Capitol', 'Atlanta', 'GA', '30334'),
      'HM-1 State Capitol, Atlanta, GA 30334')

# Semicolons and the empty segments they leave behind.
check('semicolons become commas',
      normalize_address('240 State Capitol', 'Atlanta', 'GA', '30334'),
      '240 State Capitol, Atlanta, GA 30334')
check('a semicolon inside the street line becomes a comma',
      normalize_address('206 Washington Street; Suite 203, State Capitol',
                        'Atlanta', 'GA', '30334'),
      '206 Washington Street, Suite 203, State Capitol, Atlanta, GA 30334')
check('empty segments between separators collapse',
      normalize_address('214 State Capitol ; ; ', 'Atlanta', 'GA', '30334-'),
      '214 State Capitol, Atlanta, GA 30334')

# ZIP hygiene: drop a dangling hyphen, keep a real ZIP+4.
check('a trailing-hyphen ZIP loses the hyphen',
      normalize_address('1 Somewhere', 'Atlanta', 'GA', '30334-'),
      '1 Somewhere, Atlanta, GA 30334')
check('a real ZIP+4 is preserved',
      normalize_address('40 Capitol Square, SW', 'Atlanta', 'GA', '30334-1300'),
      '40 Capitol Square, SW, Atlanta, GA 30334-1300')

check('runs of whitespace collapse',
      normalize_address('320-B    CLOB', 'Atlanta', 'GA', '30334'),
      f'320-B {CLOB}, Atlanta, GA 30334')

# Missing pieces must yield null, never a bare comma or the string "None".
check('no pieces at all -> None', normalize_address('', '', '', ''), None)
check('whitespace-only -> None', normalize_address('  ', None, None, None), None)
check('street only -> no dangling comma', normalize_address('320-B CLOB', '', '', ''),
      f'320-B {CLOB}')
check('missing street still yields the city line',
      normalize_address(None, 'Atlanta', 'GA', '30334'), 'Atlanta, GA 30334')

# ---------------------------------------------------------------------------
# Committee display names: legis.ga.gov's own names are published verbatim, so
# the list needs no maintenance as committees are renamed. The one exception is
# the bare acronym, which means nothing to a reader.
# ---------------------------------------------------------------------------
print('\nlib.ga_roster.display_committee')

check('MARTOC is expanded', display_committee('MARTOC'),
      'Metropolitan Atlanta Rapid Transit Overview Committee')
check('  and is matched case- and space-insensitively',
      display_committee(' martoc '),
      'Metropolitan Atlanta Rapid Transit Overview Committee')
check('an official name with & is published verbatim',
      display_committee('Ways & Means'), 'Ways & Means')
check('the official long form is not rewritten',
      display_committee('Special Committee on Healthcare'),
      'Special Committee on Healthcare')
check('surrounding whitespace is trimmed',
      display_committee('  Appropriations  '), 'Appropriations')
check('empty -> None', display_committee('   '), None)
check('None -> None', display_committee(None), None)


# ---------------------------------------------------------------------------
# apply_member_overrides — lifted out of generate_ga_members_data.py so the
# SOAP producer applies the SAME editorial layer. This is what carries the
# vacancy/departure data the majority tracker renders; a producer that skipped
# it would silently promote 11 Resigned + 1 Suspended member back to active.
# ---------------------------------------------------------------------------
print()
print('lib.ga_roster.apply_member_overrides')

import tempfile  # noqa: E402

from lib.ga_roster import apply_member_overrides  # noqa: E402


def _ov(tmp, payload):
    """Write an overrides file and return its path."""
    path = os.path.join(tmp, 'ov.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh)
    return path


def _base():
    return [{'id': 'ocd-person/aaa', 'name': 'Jane Doe', 'status': None},
            {'id': 'legis-99', 'name': 'John Roe', 'status': None}]


with tempfile.TemporaryDirectory() as tmp:
    # Patch by OCD id — the precise key, preferred over the name.
    ms = _base()
    got = apply_member_overrides(ms, _ov(tmp, {
        'ocd-person/aaa': {'status': 'Resigned', 'statusDate': '2026-01-05'}}))
    check('patch by OCD id applies', got, (1, 0))
    check('  status is set', ms[0]['status'], 'Resigned')
    check('  statusDate is set', ms[0]['statusDate'], '2026-01-05')
    check('  other members untouched', ms[1]['status'], None)

    # Name keys, case- and whitespace-insensitive, for members with no OCD id.
    ms = _base()
    apply_member_overrides(ms, _ov(tmp, {'  john roe ': {'status': 'Suspended'}}))
    check('patch by name is case/space-insensitive', ms[1]['status'], 'Suspended')

    # Underscore-prefixed keys are editorial notes, never published fields.
    ms = _base()
    apply_member_overrides(ms, _ov(tmp, {
        'ocd-person/aaa': {'_note': 'confirmed by AJC', 'status': 'Deceased'}}))
    check('_-prefixed keys are stripped from the patch', '_note' in ms[0], False)
    check('  the real field still applies', ms[0]['status'], 'Deceased')

    # _inject adds a member the source does not carry...
    ms = _base()
    got = apply_member_overrides(ms, _ov(tmp, {'_inject': [
        {'id': 'ocd-person/zzz', 'name': 'Vacant', 'status': 'Vacant', '_why': 'x'}]}))
    check('_inject adds a new member', got, (0, 1))
    check('  with _-keys stripped', '_why' in ms[-1], False)
    check('  roster grew by one', len(ms), 3)

    # ...and never duplicates one the source already returned. That is what makes
    # an _inject entry self-skipping once the upstream catches up.
    ms = _base()
    got = apply_member_overrides(ms, _ov(tmp, {'_inject': [
        {'id': 'ocd-person/aaa', 'name': 'Jane Doe'}]}))
    check('_inject never duplicates an existing id', (len(ms), got[1]), (2, 0))

    # A member with no id/name must not crash the name path.
    check('missing id/name does not raise',
          apply_member_overrides([{'id': None, 'name': None}],
                                 _ov(tmp, {'x': {'status': 'Vacant'}})), (0, 0))

check('a missing overrides file is not an error',
      apply_member_overrides(_base(), 'does/not/exist.json'), (0, 0))


# An _inject entry exists because the source did not carry that member. When the
# source STARTS carrying them, skipping the entry outright silently discards the
# editorial departure record with it: Open States dropped resigned members, so
# their "Resigned" lived only in _inject, and legis.ga.gov returns all 247 who
# served the biennium. That is 11 resigned members reading as sitting and 11
# empty seats painted as filled on the majority tracker. So the source's facts
# win, and the editorial status fields are merged on top.
with tempfile.TemporaryDirectory() as tmp:
    live = [{'id': 'ocd-person/aaa', 'name': 'Jane Doe', 'party': 'Republican',
             'district': 7, 'status': None, 'statusDate': None, 'statusNote': None}]
    got = apply_member_overrides(live, _ov(tmp, {'_inject': [
        {'id': 'ocd-person/aaa', 'name': 'Jane Doe', 'party': 'Democratic',
         'district': 99, 'status': 'Resigned', 'statusDate': '2026-03-13',
         'statusNote': 'resigned to run for Congress'}]}))
    check('_inject on a now-carried member counts as a patch, not an injection',
          (got, len(live)), ((1, 0), 1))
    check('  the editorial status is merged', live[0]['status'], 'Resigned')
    check('  statusDate comes with it', live[0]['statusDate'], '2026-03-13')
    check('  statusNote comes with it', live[0]['statusNote'],
          'resigned to run for Congress')
    check('  but the stale snapshot does NOT overwrite live facts: party',
          live[0]['party'], 'Republican')
    check('  ...or district', live[0]['district'], 7)

    # A sitting member whose _inject entry carries no status is left untouched --
    # these are the "source has not catalogued them yet" entries, and once the
    # source does, the entry has nothing left to contribute.
    live = [{'id': 'ocd-person/bbb', 'name': 'John Roe', 'status': None}]
    got = apply_member_overrides(live, _ov(tmp, {'_inject': [
        {'id': 'ocd-person/bbb', 'name': 'John Roe', 'status': None}]}))
    check('a status-free _inject on a carried member changes nothing', got, (0, 0))
    check('  status stays null', live[0]['status'], None)

    # An explicit patch still wins over the _inject merge: it is the more
    # specific statement about that member.
    live = [{'id': 'ocd-person/ccc', 'name': 'Ann Poe', 'status': None}]
    apply_member_overrides(live, _ov(tmp, {
        'ocd-person/ccc': {'status': 'Deceased'},
        '_inject': [{'id': 'ocd-person/ccc', 'name': 'Ann Poe',
                     'status': 'Resigned'}]}))
    check('an explicit patch outranks the _inject merge',
          live[0]['status'], 'Deceased')


# ---------------------------------------------------------------------------
# listing_is_too_short -- the gap a plain "roster count" floor cannot see.
# The producer preserves any committed member ABSENT from the source listing
# (that is how the Lt. Governor survives). So a truncated listing does not
# shrink the roster, it silently fills it with stale records: 50 fresh + 200
# carried still clears a 56/180 floor while 200 members quietly stop updating.
# Stale-but-complete is worse than short, because nothing looks wrong.
# ---------------------------------------------------------------------------
print()
print('lib.ga_roster.listing_is_too_short')

from lib.ga_roster import listing_is_too_short  # noqa: E402

check('a full listing is fine', listing_is_too_short(247, 248), False)
check('a listing larger than the roster is fine (new members)',
      listing_is_too_short(255, 248), False)
check('losing the 4 non-members is fine (the executives + Lt. Governor)',
      listing_is_too_short(247, 251), False)
check('a 10% shortfall is tolerated (an election-year turnover)',
      listing_is_too_short(224, 248), False)
check('a truncated listing is caught', listing_is_too_short(50, 248), True)
check('  even one just past the tolerance', listing_is_too_short(200, 248), True)
check('an empty listing is caught', listing_is_too_short(0, 248), True)
# A first run, or a deliberate roster reset, has nothing to compare against.
check('no committed roster -> cannot judge, so do not block',
      listing_is_too_short(247, 0), False)


print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
sys.exit(1 if FAIL else 0)
