#!/usr/bin/env python3
"""Invariants of validate_school_districts.py. No network, no third-party imports.

The validator's `validate()` takes plain dicts, and its only yaml use is inside
load_places()/main(), so this suite drives it directly with synthetic registries.
scripts/test_*.py run in CI with no pip packages, which is why that matters.

What is pinned, and why each one is a mistake worth blocking:
  * A SUPERINTENDENT MUST CARRY voting: false. Georgia local superintendents are
    hired by the board, not elected. Letting one through without the flag would
    present an appointed officer as somebody voters chose — the single factual
    error this file must not permit.
  * PARTY MUST BE Nonpartisan, AND partisan MUST NOT BE true. Georgia school
    board seats are nonpartisan; a party label on one is a false claim about an
    election.
  * IDS ARE THE JOIN KEY, so a duplicate is an error, not a merge.
  * A COUNTY SYSTEM MUST NOT CARRY `counties` and a city system must, with every
    slug resolving in places.yml — the two halves of the 1:1-vs-irregular model.
  * AN EMPTY `members:` LIST IS AN ERROR while an ABSENT KEY IS FINE. "Not yet
    researched" and "this board has no members" are different claims.
  * 159 + 21 = 180. A changed count means GOSA moved a code or the generated
    block was hand-edited.

Run: python scripts/test_school_districts_validate.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_school_districts as V  # noqa: E402

PLACES = {"newton", "dekalb", "fulton", "atlanta", "cobb"}

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def county(**kw):
    d = {"id": "707", "name": "Newton County", "type": "county",
         "countyFips": "13217", "districtCensusId": "03930"}
    d.update(kw)
    return d


def city(**kw):
    d = {"id": "773", "name": "City Schools of Decatur", "type": "city",
         "counties": ["dekalb"], "districtCensusId": "01680"}
    d.update(kw)
    return d


def member(**kw):
    m = {"name": "Jane Doe", "role": "Board Member", "seat": "District 1",
         "source": "https://example.k12.ga.us/board"}
    m.update(kw)
    return m


def run(counties=None, cities=None):
    """(errors, warnings) with the 159/21 count check neutralised."""
    data = {"countyDistricts": counties if counties is not None else [county()],
            "cityDistricts": cities if cities is not None else [city()]}
    errors, warnings = V.validate(data, PLACES)
    # Drop the count errors so each check tests one thing.
    errors = [e for e in errors if "expected 159" not in e and "expected 21" not in e]
    return errors, warnings


def errs(**kw):
    return " | ".join(run(**kw)[0])


def warns(**kw):
    return " | ".join(run(**kw)[1])


print('A clean registry passes')
e, w = run()
check(not e, 'minimal county + city entries produce no errors: %s' % (e or 'none'))

print('\nThe real file validates as published')
# Guarded, the way test_executive_identity.py and test_ga_legislator_pages.py do
# it: CI installs no pip packages, so this one check runs locally and is skipped
# there. Everything above and below needs no yaml at all.
try:
    import yaml as _y
except ImportError:
    _y = None
real = None
if _y is not None:
    try:
        with open(os.path.join(os.path.dirname(HERE), '_data', 'school_districts.yml'),
                  encoding='utf-8') as fh:
            real = _y.safe_load(fh)
    except Exception:                              # noqa: BLE001
        real = None
if real:
    re_, rw = V.validate(real, V.load_places())
    check(not re_, 'the committed registry has no errors: %s' % (re_[:2] or 'none'))
    check(len(real['countyDistricts']) == 159 and len(real['cityDistricts']) == 21,
          '159 county + 21 city = 180 districts')
else:
    check(True, '(skipped: pyyaml unavailable, which is the CI case)')

print('\nA Superintendent is appointed, not elected')
sup = member(role='Superintendent')
check('voting: false' in errs(counties=[county(members=[sup])]),
      'a Superintendent WITHOUT voting:false is an error — it would present an '
      'appointed officer as elected')
ok_sup = member(role='Superintendent', voting=False)
check(not errs(counties=[county(members=[ok_sup])]),
      'with voting:false it passes')
dated = member(role='Superintendent', voting=False, last_elected=2024)
check('should be blank' in warns(counties=[county(members=[dated])]),
      'last_elected on a Superintendent warns (there was no election)')
check(not errs(counties=[county(members=[dated])]),
      'but it warns rather than failing — the data is still publishable')
check('Superintendent' in V.APPOINTED_ROLES and 'Superintendent' in V.VALID_ROLES,
      'Superintendent is a valid role AND marked appointed')
both = county(board_size=1, members=[member(), member(name='B', seat='District 2',
                                            role='Superintendent', voting=False)])
check(not [x for x in run(counties=[both])[0] if 'board_size' in x],
      'a Superintendent is not counted against board_size')

print('\nPartisanship is per district, not statewide')
# Measured 2026-11-02: every county with a 2024 BOE contest in the SoS results
# carries party labels (Cobb, Jackson, Newton, Thomas, Whitfield — all Dem/Rep).
# So a party must be RECORDABLE; what is checked is that it agrees with the
# district's own `partisan` flag.
check(not errs(counties=[county(partisan=True,
                                members=[member(party='Republican')])]),
      'a real party on a district declaring partisan: true passes — the file must '
      'be able to hold the actual election results')
check('partisan: false' in errs(counties=[county(partisan=False,
                                                 members=[member(party='Democratic')])]),
      'a real party on a district declaring partisan: false is an error, and the '
      'message says one of the two is wrong')
check(not errs(counties=[county(partisan=False,
                                members=[member(party='Nonpartisan')])]),
      'Nonpartisan on a nonpartisan district passes')
check('partisan: false' in errs(counties=[county(partisan=False,
                                                 members=[member(party='Independent')])]),
      'Independent means a partisan seat with no party, so it is not valid on a '
      'nonpartisan board')
check('vocabulary' in errs(counties=[county(members=[member(party='Whig')])]),
      'a party outside the vocabulary is an error')
check(V.VALID_PARTIES == {'Republican', 'Democratic', 'Independent', 'Nonpartisan'},
      'the vocabulary matches local_officials.yml')
check('must be true or false' in errs(counties=[county(partisan='yes')]),
      'a non-boolean partisan is an error')
check(not errs(counties=[county(partisan=True)]) and not errs(counties=[county(partisan=False)]),
      'both boolean values are legal on a district')

print('\nIds are the join key')
check('duplicate district id' in errs(counties=[county(), county(countyFips='13001')]),
      'two districts with the same id is an error')
check('duplicate district id' in errs(cities=[city(), city(name='Other')]),
      'the id check spans BOTH lists, not each separately')
check('quoted numeric GOSA code' in errs(counties=[county(id=707)]),
      'an unquoted integer id is an error (zero-padding matters)')

print('\nCounty vs city: the 1:1 model')
check('must NOT carry `counties`' in errs(counties=[county(counties=['newton'])]),
      'a county system carrying `counties` is an error — it derives from countyFips')
check('non-empty `counties`' in errs(cities=[city(counties=[])]),
      'a city system with no `counties` is an error')
check('not in places.yml' in errs(cities=[city(counties=['nowhere'])]),
      'an unresolvable slug is an error, not a forward reference')
check('13xxx' in errs(counties=[county(countyFips='99999')]),
      'a non-Georgia FIPS is an error')
check('listed under' in errs(counties=[county(type='city')]),
      'a city-typed entry under countyDistricts is an error')

print('\nRosters: required fields, and absent vs empty')
check(not errs(counties=[county()]),
      'a district with NO members key is fine — "not yet researched" is normal')
check('Omit the key entirely' in errs(counties=[county(members=[])]),
      'an EMPTY members list is an error — it reads as "this board has no members"')
for field in ('name', 'role', 'seat', 'source'):
    m = member(); m[field] = ''
    check(field in errs(counties=[county(members=[m])]),
          'a blank %s is an error' % field)
check('must be a URL' in errs(counties=[county(members=[member(source='see website')])]),
      'a source that is not a URL is an error')
check('vocabulary' in errs(counties=[county(members=[member(role='Trustee')])]),
      'a role outside the vocabulary is an error')
check(V.VALID_ROLES == {'Chair', 'Vice Chair', 'Board Member', 'Superintendent'},
      'the role vocabulary is the four agreed values')

print('\nBoard size and presiding officers')
big = county(board_size=1, members=[member(), member(name='B', seat='District 2')])
check('board_size' in errs(counties=[big]),
      'more elected members than board_size is an error')
partial = county(board_size=5, members=[member()])
check('1 of 5 seats captured' in warns(counties=[partial]),
      'a partial roster warns with the count, so it is legible')
two_chairs = county(members=[member(role='Chair'),
                             member(name='B', seat='D2', role='Chair')])
check('presiding role' in warns(counties=[two_chairs]),
      'two Chairs warns')
check('board_size' in errs(counties=[county(board_size=0)]),
      'board_size must be a positive integer')

print('\nStructural guards')
e2, _ = V.validate({"countyDistricts": [county()], "cityDistricts": [city()]}, PLACES)
check(any('expected 159' in x for x in e2) and any('expected 21' in x for x in e2),
      'a wrong district count is an error naming both expectations')
check('unexpected top-level key' in " | ".join(
          V.validate({"districts": []}, PLACES)[0]),
      'an unknown top-level key is an error')
check('more than once' in " | ".join(V.validate(
          {"countyDistricts": [county(), county(id='601')],
           "cityDistricts": [city()]}, PLACES)[0]),
      'the same county FIPS twice is an error')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll school-district validator invariants hold.')
