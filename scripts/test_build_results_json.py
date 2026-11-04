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

import json
import os
import sys
import tempfile
import zipfile

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

print("XLSX: the shape the Secretary of State actually publishes")


def make_xlsx(path, sheets):
    """A minimal real workbook, built with the standard library.

    Written by hand rather than with openpyxl on purpose: these suites run on a
    bare runner with no pip install (.github/workflows/run-script-tests.yml), and
    a test that needs a dependency to prove the no-dependency reader works would
    prove nothing about election night. Every value is an inline string, which
    is valid XLSX and exercises a path the SoS file does not — its own shared
    strings are covered by the fixtures in _sources/election_results/.
    """
    def esc(v):
        return (str(v).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    def col(i):
        name = ''
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            name = chr(65 + rem) + name
        return name

    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('[Content_Types].xml',
                    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        rels = ''.join(
            f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            for n in range(1, len(sheets) + 1))
        zf.writestr('xl/_rels/workbook.xml.rels',
                    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + rels + '</Relationships>')
        tabs = ''.join(
            f'<sheet name="{esc(name)}" sheetId="{n}" r:id="rId{n}"/>'
            for n, (name, _) in enumerate(sheets, start=1))
        zf.writestr('xl/workbook.xml',
                    '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    f'<sheets>{tabs}</sheets></workbook>')
        for n, (_, rows) in enumerate(sheets, start=1):
            body = ''
            for ri, row in enumerate(rows, start=1):
                cells = ''.join(
                    f'<c r="{col(ci)}{ri}" t="inlineStr"><is><t>{esc(v)}</t></is></c>'
                    for ci, v in enumerate(row) if v != '')
                body += f'<row r="{ri}">{cells}</row>'
            zf.writestr(f'xl/worksheets/sheet{n}.xml',
                        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                        f'<sheetData>{body}</sheetData></worksheet>')


HEAD = ['Office Name', 'Contest ID', 'Ballot Name', 'Choice ID', 'Party', 'Total']
with tempfile.TemporaryDirectory() as d:
    book = os.path.join(d, 'export.xlsx')
    make_xlsx(book, [
        # The real workbook's first sheet is NOT the only one with these columns:
        # "County Results" repeats them per county. Reading by position would
        # parse plausible nonsense, so the sheet is resolved by NAME.
        ('County Results', [['County'] + HEAD,
                            ['Appling County', 'US Senate', 'US2', 'Mike Collins (Rep)', '1', 'Rep', '7']]),
        ('Total Votes', [HEAD,
                         ['US Senate', 'US2', 'Mike Collins (Rep)', '1', 'Rep', '1100'],
                         # A blank Choice ID mid-row: cells are ADDRESSED in XLSX,
                         # and a reader that takes them in document order shifts
                         # every later column left, putting votes in Party.
                         ['US Senate', 'US2', 'Jon Ossoff (I) (Dem)', '2', 'Dem', '1200'],
                         ['US Senate', 'US2', 'Total Votes', '', '', '2300']]),
    ])
    check('is_xlsx detects a workbook by content, not extension', brj.is_xlsx(book))
    rows = list(brj.read_rows(book))
    check('the named results sheet is the one read, not the first in the zip',
          rows[0][:6] == HEAD, str(rows[0][:6]))
    c = one(brj.parse_csv(book))
    names = [x['name'] for x in c['candidates']]
    check('a blank cell does not shift the later columns',
          c['totalVotes'] == 2300 and [x['votes'] for x in c['candidates']] == [1200, 1100],
          f'{c["totalVotes"]} / {[x["votes"] for x in c["candidates"]]}')
    check('an export that already suffixes the party is not double-suffixed',
          names == ['Jon Ossoff (Dem)', 'Mike Collins (Rep)'], str(names))
    check('(I) is still read as incumbency through the party suffix',
          c['candidates'][0]['incumbent'] is True)

print('Office names: a trailing qualifier the rest of the site does not use')
sections = brj.build_sections(parse([
    'District Attorney - Atlantic Judicial Circuit (Special Primary),SDA5,Laurie E. Baio,48,,10',
]))
courts = [s for s in sections if s['id'] == 'courts'][0]
check('the qualifier is dropped so the name matches races.json and race_notes',
      [r['office'] for r in courts['races']] == ['District Attorney - Atlantic Judicial Circuit'],
      str([r['office'] for r in courts['races']]))

# The guard that makes the strip safe: here the qualifier is the ONLY difference,
# so dropping it would merge a special election into the regular race's card and
# add the two sets of candidates together.
sections = brj.build_sections(parse([
    'District Attorney - Southern Judicial Circuit,SDA9,Pat Regular,1,DEM,10',
    'District Attorney - Southern Judicial Circuit (Special),SDA9S,Sam Special,2,REP,20',
]))
courts = [s for s in sections if s['id'] == 'courts'][0]
offices = sorted(r['office'] for r in courts['races'])
check('a qualifier that is the only thing telling two races apart is KEPT',
      offices == ['District Attorney - Southern Judicial Circuit',
                  'District Attorney - Southern Judicial Circuit (Special)'],
      str(offices))

sections = brj.build_sections(parse([
    'State House of Representatives - District 51,SHD51,Aaron Baker,1,DEM,10',
    'State House of Representatives - District 51 (Special),SHD51S,Jane Doe,2,REP,20',
]))
house = [s for s in sections if s['id'] == 'state-house'][0]
check('a special legislative race stays its own card',
      len(house['races']) == 2, str([r['office'] for r in house['races']]))

print('Carry-forward: a wholesale rename is not a partial report')
measures_baseline = [{'id': 'measures', 'label': 'Ballot Questions', 'races': [
    {'office': 'Constitutional Amendment \u2014 Authorize Creation of Next Generation 9-1-1 Fund Amendment',
     'contests': [{'party': 'np', 'totalVotes': 0, 'candidates': [
         {'name': 'Yes', 'votes': 0, 'incumbent': False}]}]},
]}]
sections = brj.build_sections(parse([
    'Proposed Constitutional Amendment 1,SQ1,Yes,1,,500',
    'Proposed Constitutional Amendment 1,SQ1,No,2,,400',
]))
carried = brj.fill_missing_races(sections, measures_baseline)
measures = [s for s in sections if s['id'] == 'measures'][0]
check('the export\'s names win when no baseline name matches and it is no shorter',
      carried == 0 and len(measures['races']) == 1,
      f'carried {carried}, {[r["office"] for r in measures["races"]]}')

# The distinction that makes the rule safe: 1 reported race out of 3 is a
# partial report, not a rename, even though nothing it reports is new.
partial_baseline = [{'id': 'state-house', 'label': 'GA State House', 'races': [
    {'office': f'District {n}', 'contests': [
        {'party': 'np', 'totalVotes': 0, 'candidates': [{'name': 'X', 'votes': 0, 'incumbent': False}]}]}
    for n in (1, 2, 3)]}]
sections = brj.build_sections(parse([
    'State House of Representatives - District 99,SHD99,New Person,1,DEM,10',
]))
carried = brj.fill_missing_races(sections, partial_baseline)
check('a short export still carries the baseline forward', carried == 3, str(carried))

print('JSON feed: the form with a stable URL')
FEED = {
    'electionDate': '2026-11-03',
    'createdAt': '2026-11-04T00:14:40.337107Z',
    'results': {'name': 'Georgia', 'ballotItems': [
        {'type': 'State', 'id': 'US2', 'name': 'US Senate', 'contestType': 'Candidate',
         'ballotOptions': [
             {'id': '1', 'name': 'Mike Collins (Rep)', 'voteCount': 231911, 'politicalParty': 'Rep'},
             {'id': '2', 'name': 'Jon Ossoff (I) (Dem)', 'voteCount': 563565, 'politicalParty': 'Dem'},
         ]},
        {'type': 'State', 'id': 'SQ1', 'name': 'Proposed Constitutional Amendment 1',
         'contestType': 'Candidate', 'ballotOptions': [
             {'id': '32', 'name': 'Yes', 'voteCount': 300, 'politicalParty': None},
             {'id': '33', 'name': 'No', 'voteCount': 200, 'politicalParty': None},
         ]},
    ]},
}
with tempfile.TemporaryDirectory() as d:
    feed = os.path.join(d, 'export.json')
    with open(feed, 'w', encoding='utf-8') as fh:
        json.dump(FEED, fh)
    check('is_json_export recognizes the feed', brj.is_json_export(feed))
    contests, created = brj.parse_export(feed)
    check("the feed's own createdAt is returned for the stamp",
          created == '2026-11-04T00:14:40.337107Z', str(created))
    sen = contests['US2']
    names = [x['name'] for x in sen['candidates']]
    check('both parties under one ballot item become one neutral contest',
          sen['party'] == 'np', sen['party'])
    check('candidates keep their own party and are sorted by votes',
          names == ['Jon Ossoff (Dem)', 'Mike Collins (Rep)'], str(names))
    check('(I) is read as incumbency, not kept in the name',
          sen['candidates'][0]['incumbent'] is True)
    # The feed has no per-contest "Total Votes" row at all.
    check('the total is summed from the ballot options',
          sen['totalVotes'] == 795476, str(sen['totalVotes']))
    measure = contests['SQ1']
    check('a ballot question stays np with bare option names',
          measure['party'] == 'np'
          and [x['name'] for x in measure['candidates']] == ['Yes', 'No'])

    empty = os.path.join(d, 'empty.json')
    with open(empty, 'w', encoding='utf-8') as fh:
        json.dump({'electionDate': '2026-11-03', 'results': {'ballotItems': []}}, fh)
    try:
        brj.parse_export(empty)
        check('a feed with no ballotItems is refused', False, 'no error raised')
    except ValueError:
        check('a feed with no ballotItems is refused', True)

if FAILURES:
    print(f'\n{len(FAILURES)} check(s) failed: {", ".join(FAILURES)}')
    sys.exit(1)
print('\nAll checks passed.')
