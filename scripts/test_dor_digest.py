#!/usr/bin/env python3
"""Invariants of the DOR digest reader (lib/xlsx.py + lib/dor_digest.py). No network.

The fixtures are REAL DOR data, cut down: scripts/fixtures/dor-digest-2023.xlsx
and -2025.xlsx hold every one of the workbook's 425 columns (so a DOR column
rename still fails this suite) but only six counties — Appling, Carroll, DeKalb,
Henry, Miller and Newton. Those six were chosen because between them they
exercise every way the source misbehaves. They were written with the standard
library from the real 2023 and 2025 workbooks, preserving the originals' sparse
cells, shared strings and numeric-vs-text cell types.

No third-party imports anywhere in the chain: run-script-tests.yml installs no
pip packages, so an openpyxl-based reader could never be checked here. That is
why lib/xlsx.py exists.

What is pinned, and why:
  * THE NAME DRIFT, in both directions. Appling's school line is 'SCHOOL' in 2023
    and 'Appling County - SCHOOL' in 2025; Newton's is
    'Newton County - Newton School' in 2023 and 'SCHOOL' in 2025. Miller's
    library drifts 'COUNTY WIDE LIBRARY' -> 'Countywide Library'. Joining on name
    would fragment 15% of the statewide series into phantom new districts, so the
    key is (countyCode, districtCode, taxYear) and these pairs must survive it.
  * DISTRICT CODES MEAN SOMETHING ONLY BELOW 4. Codes 1/2/3 are state/school/
    county-incorporated in every county. Code 15 is COUNTY UNINCORPORATED in
    Appling and the city of NEWBORN in Newton — the same code, two kinds of
    thing — so anything above 3 must classify by name.
  * CITY SCHOOL SYSTEMS, under all their spellings. Carroll's Carrollton system
    is 'IND SCHOOL CARROLLTON' in 2023 and 'Carrollton City Schools' in 2025;
    Bremen's is 'IND SCHOOL BREMEN 40%' then 'Bremen Schools'. Atlanta appears
    under DeKalb as well as Fulton. Misfiling one as the county system would
    double-count a school district on a place page.
  * A BLANK IS NOT A ZERO. Appling's code-0 countywide row has no millage (None),
    while its STATE row levies a real 0.0. Collapsing the two would publish
    "0 mills" for a county that simply reported nothing.
  * FLOAT ARTIFACTS ARE ROUNDED ONCE. The workbook stores 7414236.4699999997.
  * A LAYOUT CHANGE REFUSES. Dropping or renaming a required column raises
    DigestError instead of publishing a column of blanks.

Run: python scripts/test_dor_digest.py
"""

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import xlsx  # noqa: E402
from lib import dor_digest as D  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = lambda y: os.path.join(HERE, 'fixtures', 'dor-digest-%s.xlsx' % y)  # noqa: E731

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def raises(fn, needle):
    try:
        fn()
    except Exception as exc:                      # noqa: BLE001 - any failure, loudly
        return needle.lower() in str(exc).lower()
    return False


REC = {}
for year in ('2023', '2025'):
    REC[year] = {(r['countyCode'], r['districtCode']): r for r in D.parse(FIX(year))}


def rec(year, cc, dc):
    return REC[year].get((cc, dc))


print('xlsx reader')
check(xlsx.col_index('A1') == 0 and xlsx.col_index('Z9') == 25
      and xlsx.col_index('AA1') == 26 and xlsx.col_index('PI1') == 424,
      'column refs decode as bijective base-26 (A->0, Z->25, AA->26, PI->424)')
check(raises(lambda: xlsx.col_index('17'), 'no column letters'),
      'a cell ref with no letters refuses instead of defaulting to column 0')
hdr = next(xlsx.padded_rows(FIX('2025')))
check(len(hdr) == 425, 'fixture keeps all 425 columns, so a DOR rename fails here: %d' % len(hdr))
check(hdr[:5] == ['County Name', 'County Code', 'District Name', 'District Code', 'Tax Year'],
      'shared strings resolve to text, not to their integer index')
check(hdr[-4:] == ['Millage Rate-M&O', 'Millage Rate-Bond', 'Total Tax-M&O', 'Total Tax-Bond'],
      'the four levy columns are last and intact')
widths = {len(r) for r in xlsx.padded_rows(FIX('2025'))}
check(widths == {425},
      'every row is padded to the header width, so the trailing levy columns '
      'cannot vanish from a sparse row: %r' % sorted(widths))
check(len(xlsx.sheet_names(FIX('2023'))) == 1, 'sheet resolves through the workbook rels')

print('\nRule 1 - the key is codes, and names drift under it')
for cc, dc, n23, n25, label in (
        ('1', '2', 'SCHOOL', 'Appling County - SCHOOL', 'Appling school: bare -> prefixed'),
        ('107', '2', 'Newton County - Newton School', 'SCHOOL', 'Newton school: prefixed -> bare'),
        ('100', '11', 'COUNTY WIDE LIBRARY', 'Countywide Library', 'Miller library: wording + casing'),
        ('1', '20', 'COUNTY FIRE DIST', 'Appling County - COUNTY FIRE', 'Appling fire: renamed'),
        ('107', '10', 'Newton County - Mansfield', 'MANSFIELD', 'Newton Mansfield: prefixed -> bare')):
    a, b = rec('2023', cc, dc), rec('2025', cc, dc)
    check(a is not None and b is not None and a['districtName'] == n23 and b['districtName'] == n25,
          '%s — same (%s,%s) across years, different name' % (label, cc, dc))
check(rec('2023', '1', '2')['districtType'] == rec('2025', '1', '2')['districtType'] == 'school',
      'a renamed district keeps its type across years')
for year in ('2023', '2025'):
    recs = D.parse(FIX(year))
    check(len({D.key(r) for r in recs}) == len(recs),
          '%s: every (countyCode, districtCode, taxYear) is unique' % year)

print('\nRule 2 - codes 0-3 are statewide, above that the name decides')
check(rec('2025', '1', '1')['districtType'] == 'state', 'code 1 -> state')
check(rec('2025', '1', '2')['districtType'] == 'school', 'code 2 -> county school system')
check(rec('2025', '1', '3')['districtType'] == 'county_incorporated', 'code 3 -> county incorporated')
check(rec('2025', '1', '15')['districtType'] == 'county_unincorporated',
      "code 15 in Appling is COUNTY UNINCORPORATED")
check(rec('2025', '107', '15')['districtType'] == 'city'
      and rec('2025', '107', '15')['districtName'] == 'NEWBORN',
      "code 15 in Newton is the city of NEWBORN — same code, different thing")
check(rec('2025', '44', '0')['districtType'] == 'countywide'
      and rec('2025', '1', '0')['districtType'] == 'countywide',
      'code 0 is kept and classified as the countywide roll-up, not dropped')
check(rec('2025', '75', '3')['districtName'] == 'COUNTY INC - HAMPTON'
      and rec('2025', '75', '3')['districtType'] == 'county_incorporated',
      "Henry's per-city 'COUNTY INC - <CITY>' rows still read as county_incorporated")
check(rec('2025', '75', '36')['districtType'] == 'ssd',
      "'SSD UNINCORPORATED' is a special service district, not county_unincorporated")
unclassified = [r['districtName'] for y in REC for r in REC[y].values()
                if r['districtType'] == 'unclassified']
check(not unclassified, 'nothing lands in unclassified: %r' % unclassified[:5])

print('\nRule 3 - city school systems, under every spelling')
for year, cc, dc, name in (('2023', '22', '57', 'IND SCHOOL CARROLLTON'),
                           ('2025', '22', '57', 'Carrollton City Schools'),
                           ('2023', '22', '75', 'IND SCHOOL BREMEN 40%'),
                           ('2025', '22', '75', 'Bremen Schools'),
                           ('2025', '44', '17', 'IND SCHOOL ATLANTA'),
                           ('2025', '44', '67', 'IND SCHOOL DECATUR 50%'),
                           ('2025', '107', '47', 'IND SCHOOL SOCIAL CIRCLE')):
    r = rec(year, cc, dc)
    check(r is not None and r['districtName'] == name and r['districtType'] == 'city_school',
          '%s %s -> city_school' % (year, name))
check(rec('2025', '44', '17')['millageMO'] == 20.5,
      'Atlanta levies 20.5 mills in DeKalb as well as Fulton (multi-county service area)')
check(rec('2025', '44', '67')['districtName'].endswith('50%'),
      "a partial-levy suffix ('50%') is data and survives into the record")

print('\nRule 4/5 - blanks, zeros and rounding')
check(rec('2025', '1', '0')['millageMO'] is None,
      "Appling's countywide row reports no millage -> None")
check(rec('2025', '1', '1')['millageMO'] == 0.0,
      "Appling's STATE row levies a real 0.0, which is not None")
check(rec('2025', '1', '1')['millageMO'] is not None, 'a real zero is not collapsed into a blank')
check(rec('2025', '1', '3')['totalTaxMO'] == 7414236.47,
      'the stored float artifact 7414236.4699999997 is rounded once, to cents: %r'
      % rec('2025', '1', '3')['totalTaxMO'])
check(rec('2025', '1', '2')['millageMO'] == 11.273, 'millage keeps three decimals')
check(D.to_number('', 3) is None and D.to_number('  ', 3) is None, 'blank -> None')
check(D.to_number('1,234.5', 2) == 1234.5, 'thousands separators are tolerated')
check(raises(lambda: D.to_number('n/a', 2), 'not a number'), 'junk refuses instead of becoming 0')

print('\nNormalisation (classification only, never the published label)')
check(D.normalize_district_name('Appling County - SCHOOL', 'APPLING') == 'SCHOOL',
      'a "<County> County - " prefix is stripped case-insensitively')
check(D.normalize_district_name('Newton County - Newton School', 'NEWTON') == 'NEWTON SCHOOL',
      'only the prefix goes; the rest of the name is preserved')
check(D.normalize_district_name('  COUNTY  WIDE   LIBRARY ', 'MILLER') == 'COUNTY WIDE LIBRARY',
      'whitespace is collapsed and the name upper-cased')
check(rec('2025', '1', '2')['districtName'] == 'Appling County - SCHOOL',
      'the PUBLISHED name is the source string, not the normalised one')

print('\nRule 4 - a repeated key is numbered, never merged or dropped')
r25 = D.parse(FIX('2025'))
check(all(x['occurrence'] == 1 for x in r25),
      'every fixture row is occurrence 1 (the duplicate lives in DOR 2022 Cherokee, '
      'which is outside these six counties)')
check(D.key(rec('2025', '1', '2')) == ('1', '2', 2025, 1),
      'key() carries the occurrence ordinal: %r' % (D.key(rec('2025', '1', '2')),))
check(D.duplicate_groups(r25) == [], 'a clean year reports no duplicate groups')
# Synthesised: two rows sharing a key must number 1 and 2 and be reported.
twin = [dict(rec('2025', '1', '2')), dict(rec('2025', '1', '2'))]
for i, x in enumerate(twin, 1):
    x['occurrence'] = i
groups = D.duplicate_groups(twin)
check(len(groups) == 1 and len(groups[0][3]) == 2,
      'duplicate_groups surfaces a repeated (county, district, year)')
check({D.key(x) for x in twin} == {('1', '2', 2025, 1), ('1', '2', 2025, 2)},
      'the ordinal keeps repeated rows distinguishable rather than colliding')

print('\nFailure modes')


def _mutated(src, swap_from, swap_to):
    """Rewrite the fixture's sharedStrings to rename or blank a column header."""
    out = os.path.join(HERE, 'fixtures', '_tmp-mutated.xlsx')
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in zin.namelist():
            data = zin.read(item)
            if item == 'xl/sharedStrings.xml':
                data = data.replace(swap_from.encode(), swap_to.encode())
            zo.writestr(item, data)
    return out


renamed = _mutated(FIX('2025'), '<t xml:space="preserve">Millage Rate-M&amp;O</t>',
                   '<t xml:space="preserve">Millage M and O</t>')
check(raises(lambda: D.parse(renamed), 'layout has changed'),
      'a renamed millage column refuses (layout change), it does not publish blanks')
check(raises(lambda: D.parse(renamed), 'Millage Rate-M&O'),
      'the refusal names the missing column')
dropped = _mutated(FIX('2025'), '<t xml:space="preserve">District Code</t>',
                   '<t xml:space="preserve">Dist Code</t>')
check(raises(lambda: D.parse(dropped), 'layout has changed'),
      'a renamed identity column refuses too')
os.remove(renamed) if os.path.exists(renamed) else None
check(raises(lambda: xlsx.rows(__file__).__next__(), 'xlsx'),
      'a non-xlsx file refuses rather than yielding garbage')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll DOR digest reader invariants hold.')
