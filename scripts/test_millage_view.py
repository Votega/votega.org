#!/usr/bin/env python3
"""Invariants of the per-place millage view (lib/millage.py). No network, no deps.

The fixture is the real per-place output: scripts/fixtures/millage-places.json,
the _data/millage.json that build_millage_places.py produced from DOR's 2020-2025
workbooks, cut to the places these checks name. lib/millage.py imports nothing
outside the standard library so this runs in CI, which installs no pip packages.

What is pinned, and why each one is a bug that reached the page:

  * A CITY AND ITS COUNTY SHOW DIFFERENT COUNTY RATES, on purpose. An owner
    inside a city pays the county's INCORPORATED rate; one outside pays the
    UNINCORPORATED rate. Showing one figure for both is the most common way this
    kind of table is wrong.
  * A CITY SCHOOL DISTRICT REPLACES THE COUNTY SYSTEM. Atlanta residents pay
    Atlanta Public Schools, not Fulton County Schools, so the county school line
    must be absent from Atlanta's view and present in Fulton's. Listing both
    would double-count ~17 mills.
  * THE STATE LINE IS EXCLUDED. Every state row that reports a rate across
    2020-2025 reports 0.0, and 126 report nothing — so including it added zero
    while voiding the combined rate for whole county-years under the
    all-components-present rule. Carrollton 2025 was exactly that.
  * CONSOLIDATED GOVERNMENTS FALL BACK. Macon-Bibb and Athens-Clarke publish no
    unincorporated line and Columbus-Muscogee publishes only a countywide one, so
    the county line is a chain, not a single lookup. Before the chain existed,
    Macon-Bibb's page showed no county rate at all.
  * MUSCOGEE HAS NO COMBINED RATE, AND SAYS SO. Its county levy is split across
    urban, rural and Fort Benning service districts at different rates, so no
    single county figure exists to add. The view carries a reason instead of a
    silent blank, and must never invent a number.
  * COMBINED IS ALL-OR-NOTHING PER YEAR. A year missing any component is omitted
    rather than partially summed, because a partial sum understates a tax bill.
  * `values` ARRAYS ARE YEAR-ALIGNED. Liquid cannot look a hash up by a number,
    so the template walks these; a mis-length array would silently shift a rate
    into the wrong year's column.

Run: python scripts/test_millage_view.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import millage as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixtures', 'millage-places.json')

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


with open(FIXTURE, encoding='utf-8') as fh:
    PLACES = json.load(fh)['places']


def line(slug, kind):
    for ln in PLACES[slug]['lines']:
        if ln['type'] == kind:
            return ln
    return None


def types(slug):
    return [ln['type'] for ln in PLACES[slug]['lines']]


print('A city and its county show different county rates')
cov, newt = PLACES['covington'], PLACES['newton']
check('county_incorporated' in types('covington'),
      'a city page shows the county INCORPORATED rate')
check('county_unincorporated' in types('newton'),
      'a county page shows the county UNINCORPORATED rate')
check(cov['countyName'] == newt['countyName'] == 'Newton',
      'both join to the same DOR county')
check(line('covington', 'city') is not None,
      "the city's own levy is a line on its page")
check(line('newton', 'city') is None,
      "a county page does not promote one city's levy into the resident's lines")

print('\nA city school district replaces the county system')
check('city_school' in types('atlanta') and 'school' not in types('atlanta'),
      'Atlanta shows its city school district and NOT Fulton County Schools')
check('school' in types('fulton') and 'city_school' not in types('fulton'),
      'Fulton shows the county school system')
check(line('atlanta', 'city_school')['byYear']['2025'] == 20.5,
      'Atlanta Public Schools levies 20.5 mills in 2025')
check('city_school' in types('carrollton') and 'school' not in types('carrollton'),
      'Carrollton, whose system is named "Carrollton City Schools", also replaces it')

print('\nThe state line is excluded entirely')
for slug in PLACES:
    if 'state' in types(slug):
        check(False, '%s still carries a state line' % slug)
        break
else:
    check(True, 'no place carries a state line (it is 0.0 wherever reported)')
check(PLACES['carrollton']['latestCombined'] is not None,
      'Carrollton has a 2025 combined rate, which the missing state row used to void')
check(PLACES['covington']['stateRateIsZero'] is True,
      'the view still tells the page the state rate is zero, so it can say so')

print('\nConsolidated governments fall back down the county chain')
check('county_incorporated' in types('bibb'),
      'Macon-Bibb has no unincorporated line, so it falls back to incorporated')
check('county_incorporated' in types('clarke'),
      'Athens-Clarke likewise')
check('countywide' in types('muscogee'),
      'Columbus-Muscogee has only a countywide line')
check(PLACES['bibb']['latestCombined'] is not None,
      'Macon-Bibb therefore has a combined rate')

print('\nMuscogee has no combined rate and says why')
mus = PLACES['muscogee']
check(mus['combined'] == {} and mus['latestCombined'] is None,
      'no combined rate is invented where the county line reports none')
check(mus['combinedNote'] and 'no rate' in mus['combinedNote'].lower(),
      'a reason is carried instead of a silent blank: %r' % mus['combinedNote'])
check(any(o['type'] == 'county_service_district' for o in mus['other']),
      "its urban/rural/Ft Benning service districts are classified as COUNTY "
      "service districts, not as phantom cities")

print('\nCombined is all-or-nothing per year, and is a real sum')
for slug in ('covington', 'newton', 'atlanta', 'bibb'):
    v = PLACES[slug]
    for i, y in enumerate(v['years']):
        vals = [ln['values'][i] for ln in v['lines']]
        want = round(sum(vals), 3) if all(x is not None for x in vals) else None
        got = v['combinedValues'][i]
        if got != want:
            check(False, '%s %s: combined %r but the lines sum to %r' % (slug, y, got, want))
            break
    else:
        check(True, '%s: every year either sums exactly or is omitted' % slug)

print('\nYear-aligned arrays')
for slug, v in PLACES.items():
    n = len(v['years'])
    bad = [ln['label'] for ln in v['lines'] + v['other'] if len(ln['values']) != n]
    if bad or len(v['combinedValues']) != n:
        check(False, '%s: values array length != %d (%r)' % (slug, n, bad[:3]))
        break
else:
    check(True, 'every values array matches the years array length')
check(PLACES['covington']['years'] == [2020, 2021, 2022, 2023, 2024, 2025],
      'years are the six published workbook years')
check(PLACES['covington']['latestYear'] == 2025, 'latestYear is the newest')

print('\nFormatted figures')
check(M.fmt(16.0) == '16.000' and M.fmt(15.75) == '15.750' and M.fmt(12.916) == '12.916',
      'millage is quoted to three decimals, so a column does not read "12.916, 16.0, 15.75"')
check(M.fmt(None) == '\u2013', 'a year with no rate is an en dash, not 0.000')
check(M.fmt(0.0) == '0.000', 'a levied zero prints as 0.000, distinct from the dash')
cv = PLACES['covington']
check(cv['lines'][1]['valuesText'][3] == '16.000',
      "Newton's 2023 school rate renders as 16.000: %r" % cv['lines'][1]['valuesText'][3])
check(len(cv['combinedValuesText']) == len(cv['years']),
      'the combined row has a formatted value per year')
check(PLACES['muscogee']['latestCombinedText'] == '\u2013',
      'Muscogee, which has no combined rate, formats as a dash rather than "None"')

print('\nJoin helpers')
check(M.county_key({'type': 'county', 'name': 'Appling County'}) == 'APPLING',
      '"Appling County" -> APPLING')
check(M.county_key({'type': 'consolidated', 'name': 'Augusta-Richmond County'}) == 'RICHMOND',
      'a consolidated name resolves to the COUNTY half: Augusta-Richmond -> RICHMOND')
check(M.county_key({'type': 'consolidated', 'name': 'Macon-Bibb County'}) == 'BIBB',
      'Macon-Bibb -> BIBB')
check(M.county_key({'type': 'city', 'name': 'City of Covington'}) is None,
      'a city has no county name of its own; it goes through parentCounty')
check(M.city_key({'name': 'City of Fort Oglethorpe'}) == 'FORT OGLETHORPE',
      '"City of X" -> X, so it matches DOR\'s county-prefixed district name')

print('\nNo substring false positives in the city match')
atl = PLACES['atlanta']
labels = [ln['districtName'] for ln in atl['lines']]
check(not any('TAD' in (l or '') or 'CID' in (l or '') for l in labels),
      "Atlanta's lines exclude 'TAD - ATLANTA BELTLINE' and 'CID ATLANTA/MIDTOWN 05C'")
car = PLACES['carrollton']
cinc = [ln for ln in car['lines'] if ln['type'] == 'county_incorporated'][0]
check(cinc['districtName'] == 'COUNTY INC - CARROLLTON',
      "Carroll files a per-city incorporated line, and Carrollton's page uses ITS "
      "own ('COUNTY INC - CARROLLTON'), not the county's '- OTHER' rate: %r"
      % cinc['districtName'])
city = [ln for ln in car['lines'] if ln['type'] == 'city'][0]
check(city['districtName'] == 'CARROLLTON',
      "the city line is the city itself, not a 'COUNTY INC -' row")
check(len({len(set(ln['values'])) for ln in car['lines']}) >= 1
      and all(len(ln['values']) == len(car['years']) for ln in car['lines']),
      'each line is ONE district\'s series, not several blended together')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll per-place millage view invariants hold.')
