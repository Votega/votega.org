#!/usr/bin/env python3
"""Guard the two things the GENERAL-election results build does that no primary build exercises.

scripts/build_results_json.py has shipped four elections — two primaries, two
specials — and every one of them was a per-party export: each party's contest
had its own Contest ID ("US Senate - Rep" / US2R), and each contest carried a
"Total Votes" summary row. The November general export is shaped differently in
both respects, and both differences fail quietly rather than loudly:

  1. MIXED PARTY IN ONE CONTEST. A general contest holds the Democrat and the
     Republican under a single Contest ID. Taking the contest's party from its
     first row badged and bar-colored the whole card with whichever party the
     Secretary of State listed first. A page of correct numbers under wrong
     party labels is worse than no page.

  2. NO "Total Votes" ROW. ResultsContest.status() treats a falsy totalVotes as
     'no-results', so such a contest renders "Awaiting Results" and hides its
     counts — indistinguishable, at 9pm, from a race that has not reported.

Both are checked here against synthetic CSVs, plus the primary shape, so the
fixes cannot regress the four pages already published.

Usage:
  python scripts/test_build_results_json.py

Exits 0 on success, 1 on any failure.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_results_json as brj  # noqa: E402

HEADER = 'Office Name,Contest ID,Ballot Name,Choice ID,Party,Total\n'
FAILURES = []


def check(label, condition, detail=''):
    if condition:
        print(f'  PASS {label}')
    else:
        print(f'  FAIL {label}{" — " + detail if detail else ""}')
        FAILURES.append(label)


def parse(rows):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'in.csv')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(HEADER)
            fh.writelines(r if r.endswith('\n') else r + '\n' for r in rows)
        return brj.parse_csv(path)


def one(contests):
    assert len(contests) == 1, contests
    return list(contests.values())[0]


print('General export: one contest, both parties')
c = one(parse([
    'US Senate,US2,Jon Ossoff (I),1,DEM,1200',
    'US Senate,US2,Mike Collins,2,REP,1100',
    'US Senate,US2,Total Votes,,,2300',
]))
names = [x['name'] for x in c['candidates']]
check('contest is non-partisan, not the first row\'s party', c['party'] == 'np', c['party'])
check('each candidate carries their own party suffix',
      names == ['Jon Ossoff (Dem)', 'Mike Collins (Rep)'], str(names))
check('incumbency survives the suffix', c['candidates'][0]['incumbent'] is True)
check('per-candidate party is not emitted into the data',
      all('party' not in x for x in c['candidates']))
check('a real Total Votes row is used verbatim', c['totalVotes'] == 2300, str(c['totalVotes']))

print('Primary export: one party per contest (the four published pages)')
contests = parse([
    'US Senate - Rep,US2R,Mike Collins,1,REP,369642',
    'US Senate - Rep,US2R,Derek Dooley,2,REP,275534',
    'US Senate - Rep,US2R,Total Votes,,,645176',
    'US Senate - Dem,US2D,Jon Ossoff (I),3,DEM,1042331',
    'US Senate - Dem,US2D,Total Votes,,,1042331',
])
rep, dem = contests['US2R'], contests['US2D']
check('single-party contest keeps its party', (rep['party'], dem['party']) == ('rep', 'dem'))
check('single-party candidates get no suffix',
      [x['name'] for x in rep['candidates']] == ['Mike Collins', 'Derek Dooley'])
check('candidates sort by votes, descending', rep['candidates'][0]['votes'] == 369642)

print('No Total Votes row: sum the candidates instead of reporting nothing')
c = one(parse([
    'Governor,GOV,Keisha Lance Bottoms,1,DEM,900',
    'Governor,GOV,Rick Jackson,2,REP,950',
]))
check('totalVotes is backfilled', c['totalVotes'] == 1850, str(c['totalVotes']))
check('backfilled contest is not no-results (totalVotes is truthy)', bool(c['totalVotes']))

print('A zero-vote contest stays at zero (an upcoming race must read Awaiting Results)')
c = one(parse([
    'Governor,GOV,Keisha Lance Bottoms,1,DEM,0',
    'Governor,GOV,Rick Jackson,2,REP,0',
]))
check('all-zero contest keeps totalVotes 0', c['totalVotes'] == 0, str(c['totalVotes']))

print('Ballot question: Yes/No, no party, untouched')
c = one(parse([
    'Proposed Constitutional Amendment 1,CA1,Yes,1,,500',
    'Proposed Constitutional Amendment 1,CA1,No,2,,400',
    'Proposed Constitutional Amendment 1,CA1,Total Votes,,,900',
]))
check('measure stays np with bare option names',
      c['party'] == 'np' and [x['name'] for x in c['candidates']] == ['Yes', 'No'])

print('Jungle contest already carrying (Dem)/(Rep) in the ballot name is not double-suffixed')
c = one(parse([
    'District Attorney - Southern,DA1,Jane Doe (Dem),1,DEM,10',
    'District Attorney - Southern,DA1,John Roe (Rep),2,REP,20',
]))
check('no duplicate suffix appended',
      [x['name'] for x in c['candidates']] == ['John Roe (Rep)', 'Jane Doe (Dem)'],
      str([x['name'] for x in c['candidates']]))

print('Carry-forward: a partial export must not delete the rest of the ballot')
BASELINE = [
    {'id': 'statewide', 'label': 'Executive / Statewide', 'races': [
        {'office': 'US Senate', 'contests': [
            {'party': 'rep', 'totalVotes': 0, 'candidates': [{'name': 'Mike Collins', 'votes': 0, 'incumbent': False}]},
            {'party': 'dem', 'totalVotes': 0, 'candidates': [{'name': 'Jon Ossoff', 'votes': 0, 'incumbent': True}]}]},
        {'office': 'Governor', 'contests': [
            {'party': 'np', 'totalVotes': 0, 'candidates': [{'name': 'Rick Jackson', 'votes': 0, 'incumbent': False}]}]},
        {'office': 'Attorney General', 'contests': [
            {'party': 'np', 'totalVotes': 0, 'candidates': [{'name': 'Someone', 'votes': 0, 'incumbent': False}]}]},
    ]},
    {'id': 'us-house', 'label': 'U.S. House', 'races': []},
    {'id': 'state-senate', 'label': 'GA State Senate', 'races': []},
    {'id': 'state-house', 'label': 'GA State House', 'races': []},
    {'id': 'courts', 'label': 'Courts', 'races': []},
    {'id': 'measures', 'label': 'Ballot Questions', 'races': []},
]

import copy
sections = brj.build_sections(parse([
    'Governor,GOV,Keisha Lance Bottoms,1,DEM,900',
    'Governor,GOV,Rick Jackson,2,REP,950',
    'Commissioner of Labor,LAB,New Person,3,REP,10',
]))
carried = brj.fill_missing_races(sections, copy.deepcopy(BASELINE))
statewide = [s for s in sections if s['id'] == 'statewide'][0]
offices = [r['office'] for r in statewide['races']]
check('races absent from the export are carried forward', carried == 2, str(carried))
check('baseline race order is the spine, new races appended',
      offices == ['US Senate', 'Governor', 'Attorney General', 'Commissioner of Labor'],
      str(offices))
gov = [r for r in statewide['races'] if r['office'] == 'Governor'][0]
check('a reported race is REPLACED by the export, not merged with the baseline',
      len(gov['contests']) == 1 and gov['contests'][0]['totalVotes'] == 1850)
sen = [r for r in statewide['races'] if r['office'] == 'US Senate'][0]
check('a carried-forward race keeps its zeros (still reads Awaiting Results)',
      all((c['totalVotes'] or 0) == 0 for c in sen['contests']))
check('carry-forward never invents votes',
      sum(x['votes'] for c in sen['contests'] for x in c['candidates']) == 0)

sections = brj.build_sections(parse(['Governor,GOV,Rick Jackson,1,REP,950']))
check('an empty baseline carries nothing', brj.fill_missing_races(sections, []) == 0)

if FAILURES:
    print(f'\n{len(FAILURES)} check(s) failed: {", ".join(FAILURES)}')
    sys.exit(1)
print('\nAll checks passed.')
