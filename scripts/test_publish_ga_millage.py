#!/usr/bin/env python3
"""Invariants of the millage open-data publisher. No network, no deps, no publish.

Exercises the artifact BUILDING in publish_ga_millage.py, plus the shared
pre-publish gates in lib.sibling_publish, against a tiny in-memory dataset. It
never calls the GitHub API: publish_or_dry_run only publishes when the token env
var is set, and these checks drive the builders and the validator directly.

What is pinned, and why:
  * THE PUBLISHER DOES NOT WRITE latest.json. That index belongs to
    publish_ga_local_government.py, which runs twice weekly off a different
    workflow. Both target the same repo and lib.sibling_publish PUTs each path
    individually, so whichever ran last would otherwise overwrite the other's
    index and hide half the repo's datasets.
  * IT TOUCHES ONLY millage PATHS. Same reason: the agenda-mention artifacts in
    that repo must survive a millage publish untouched.
  * THE RECORD FLOOR REFUSES A GUTTED DATASET. A well-formed but nearly empty
    build is valid JSON, so _assert_artifacts_sane passes it; min_items is what
    stops it from wiping a public dataset.
  * EVERY PUBLISHED FIELD IS DOCUMENTED. A field added to the generator without
    a note in FIELD_DOC would ship an undescribed column in the schema.
  * NULL SURVIVES AS EMPTY IN CSV, not as "None" — a reader coercing "None" to a
    number gets a wrong millage rate.

Run: python scripts/test_publish_ga_millage.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_ga_millage as P  # noqa: E402
from lib import sibling_publish as SP  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def raises(fn, needle):
    try:
        fn()
    except Exception as exc:                      # noqa: BLE001
        return needle.lower() in str(exc).lower()
    return False


FIELDS = ['taxYear', 'countyCode', 'countyName', 'countyNameAsFiled',
          'districtCode', 'districtName', 'districtType', 'occurrence',
          'millageMO', 'millageBond', 'totalTaxMO', 'totalTaxBond',
          'assessedValueMO', 'assessedValueBond', 'dataSource']


def row(year=2025, cc='1', dc='2', mill=11.273, bond=None, src='digest-xlsx'):
    return [year, cc, 'APPLING', 'APPLING', dc, 'SCHOOL', 'school', 1,
            mill, bond, 17514571.76, None, 1539813328.0, None, src]


def dataset(n):
    return {
        'metadata': {'generatedAt': '2026-11-02T00:00:00Z',
                     'source': 'DOR', 'years': [2025], 'fields': FIELDS,
                     'count': n},
        'rows': [row(dc=str(i)) for i in range(n)],
    }


def artifacts_for(n):
    blob = dataset(n)
    return {
        'data/millage.json': SP.build_json(blob),
        'data/millage.csv': P.rows_csv(FIELDS, blob['rows']),
        'data/millage.schema.json': SP.build_json(P.row_schema(FIELDS)),
        'MILLAGE.md': P.summary_md(blob['metadata'], blob['rows'], FIELDS),
    }


print('The publisher cannot drift from the generator')
import generate_ga_millage as G  # noqa: E402
check(list(G.FIELDS) == FIELDS,
      "this suite's field list matches generate_ga_millage.FIELDS; if the "
      'generator gains a column, update both: %r' % (list(G.FIELDS),))
check(set(G.FIELDS) <= set(P.FIELD_DOC),
      'every field the generator publishes has a FIELD_DOC note, so no '
      'undescribed column reaches the open-data schema: missing %r'
      % sorted(set(G.FIELDS) - set(P.FIELD_DOC)))
check(set(P.FIELD_DOC) <= set(G.FIELDS),
      'and FIELD_DOC carries no note for a field that no longer exists: %r'
      % sorted(set(P.FIELD_DOC) - set(G.FIELDS)))
check(P.NUMERIC <= set(G.FIELDS),
      'the numeric-field set names only real fields')

print('\nThe two publishers do not collide')
arts = artifacts_for(P.MIN_ROWS)
check('latest.json' not in arts,
      'the millage publisher does not write latest.json (the mentions publisher owns it)')
check(all(k == 'MILLAGE.md' or 'millage' in k for k in arts),
      'every artifact path is a millage path: %r' % sorted(arts))
check(P.REPO == 'Votega/ga-local-government',
      'it targets the SAME repo as the mentions publisher, per decision 1')
check(P.TOKEN_ENV == 'GA_LOCAL_GOVERNMENT_TOKEN',
      'and reuses that repo\'s existing token, so no new secret is needed')

print('\nThe shared pre-publish gates accept a good build')
SP._assert_artifacts_sane(dict(arts))
check(True, 'a well-formed build passes _assert_artifacts_sane')
SP.min_items('data/millage.json', 'rows', minimum=P.MIN_ROWS)(dict(arts))
check(True, 'and clears the record floor at exactly the floor')

print('\nAnd refuse a bad one')
validate = SP.min_items('data/millage.json', 'rows', minimum=P.MIN_ROWS)
check(raises(lambda: validate(artifacts_for(P.MIN_ROWS - 1)), 'need >='),
      'one row below the floor is refused — a gutted dataset is valid JSON, so '
      'only this check stops it wiping the public copy')
check(P.MIN_ROWS < 1725,
      'the floor sits BELOW one year of the workbook (%d), so DOR dropping a '
      'year is not mistaken for corruption' % P.MIN_ROWS)
check(raises(lambda: SP._assert_artifacts_sane({'data/millage.json': b''}), 'empty'),
      'an empty artifact is refused')
check(raises(lambda: SP._assert_artifacts_sane({'data/millage.json': b'{nope'}), 'not valid json'),
      'a corrupt JSON artifact is refused')
check(raises(lambda: SP._assert_artifacts_sane({}), 'no artifacts'),
      'an empty artifact set is refused')
check(raises(lambda: validate({'data/other.json': b'{}'}), 'was not built'),
      'a build missing the dataset entirely is refused')

print('\nThe schema documents every field the generator publishes')
schema = json.loads(arts['data/millage.schema.json'])
undocumented = [f for f in FIELDS if not schema['properties'].get(f, {}).get('description')]
check(not undocumented, 'no undocumented field: %r' % undocumented)
check(set(schema['properties']) == set(FIELDS),
      'the schema covers exactly the published fields')
check(schema['properties']['millageMO']['type'] == ['number', 'null'],
      'a rate is a number or null — null means none reported, which is not zero')
check(schema['properties']['districtName']['type'] == ['string', 'null'],
      'a district name is a string or null')
check('never join' in schema['properties']['districtName']['description'].lower(),
      'the schema warns that district names drift and must not be joined on')
check('not a join key' in schema['properties']['countyName']['description'].lower(),
      'and that the county name is a label, not a key')
check(schema['additionalProperties'] is False,
      'the schema is closed, so a silently added column fails a consumer loudly')

print('\n2019 comes from a different source, and says so')
md2 = arts['MILLAGE.md'].decode('utf-8')
check('dataSource' in json.loads(arts['data/millage.schema.json'])['properties'],
      'dataSource is a published, documented field')
desc = json.loads(arts['data/millage.schema.json'])['properties']['dataSource']['description']
check('millage-pdf' in desc and 'MILLAGE ONLY' in desc,
      "the schema warns that 2019's null tax and value mean 'absent from the "
      "source', not 'reported none': %r" % desc[:60])
pdf_row = row(year=2019, mill=14.102, src='millage-pdf')
pdf_row[FIELDS.index('totalTaxMO')] = None
pdf_row[FIELDS.index('assessedValueMO')] = None
text19 = P.rows_csv(FIELDS, [pdf_row]).decode('utf-8')
import csv as _c0, io as _i0  # noqa: E402
p19 = list(_c0.DictReader(_i0.StringIO(text19)))[0]
check(p19['dataSource'] == 'millage-pdf' and p19['totalTaxMO'] == ''
      and p19['millageMO'] == '14.102',
      'a 2019 row carries its millage and an empty tax column, tagged millage-pdf')

print('\nCSV round-trip')
import csv as _csv  # noqa: E402
import io as _io  # noqa: E402
text = P.rows_csv(FIELDS, [row(mill=None, bond=0.0)]).decode('utf-8')
parsed = list(_csv.DictReader(_io.StringIO(text)))
check(len(parsed) == 1 and parsed[0]['millageMO'] == '',
      'a null rate is an EMPTY csv cell, never the string "None"')
check(parsed[0]['millageBond'] == '0.0',
      'a levied zero is written as 0.0, so it stays distinguishable from null')
check(parsed[0]['countyName'] == 'APPLING' and parsed[0]['districtType'] == 'school',
      'identity columns survive the round-trip')
check(text.splitlines()[0].split(',') == FIELDS,
      'the header row is the published field list, in order')

print('\nThe README states the traps a reuser would otherwise hit')
md = arts['MILLAGE.md'].decode('utf-8')
for needle, why in (
        ('countyCode', 'names the key'),
        ('Do not join', 'warns against joining on names'),
        ('null', 'explains null vs zero'),
        ('occurrence', 'explains the duplicate-row ordinal'),
        ('excluding-charlton', 'flags the 2020 workbook caveat'),
        ('each county it serves', 'warns a city school system appears more than once')):
    check(needle in md, 'MILLAGE.md %s' % why)

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll millage publisher invariants hold.')
