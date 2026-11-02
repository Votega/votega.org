#!/usr/bin/env python3
"""Invariants of the 2019 millage-PDF bridge (lib/dor_millage_pdf.py). No network.

The fixture is real text: scripts/fixtures/dor-millage-2019.txt is the 2019
"Georgia County Ad Valorem Tax Digest Millage Rates" PDF's own poppler output,
cut to four counties chosen because between them they exercise every branch —
Appling (ordinary), Bartow (TAD rows that levy NOTHING), Henry (per-city
`COUNTY INC - <CITY>` rows that do not exist in 2020), Muscogee (urban service
districts, some of which also vanish by 2020).

NOTHING HERE SHELLS OUT TO pdftotext. scripts/test_*.py run in CI with no pip
packages and no poppler, so the parser is split: parse_text() takes already
extracted text, parse() is the thin wrapper that calls poppler. This suite drives
parse_text().

What is pinned, and why:
  * 2019 IS KEYED WITH BORROWED CODES, BY EXACT NAME, AND ONLY THAT. The PDF has
    no county or district code, and the published key is
    (countyCode, districtCode, taxYear, occurrence). Names are matched exactly
    against the adjacent workbook year; a row that does not resolve is DROPPED
    and reported, never given an invented code, because a synthetic code would
    fork the series into a phantom district.
  * AN AMBIGUOUS NAME DOES NOT RESOLVE. If one normalised name maps to two
    district codes in the reference year, it is excluded from the index rather
    than guessed.
  * A ROW WITH NO MILLAGE IS KEPT, with a null rate — 85 of them statewide,
    almost all tax allocation districts that levy nothing. The workbooks record
    those the same way, and dropping them would misstate which districts existed.
  * 2019 CARRIES NO TAX AND NO ASSESSED VALUE, and says so via dataSource. In
    this dataset a null otherwise means "the jurisdiction reported none", which
    for 2019 would be false.
  * A SCANNED YEAR REFUSES. 2021 and 2024 are images and 2025 is Type 3
    mojibake; pdf_text() rejects a near-empty extraction rather than silently
    producing an empty year.

Run: python scripts/test_dor_millage_pdf.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import dor_millage_pdf as P  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixtures', 'dor-millage-2019.txt')
TEXT = open(FIXTURE, encoding='utf-8').read()

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


def ref(*rows):
    """Minimal reference-year records: (countyCode, countyName, districtCode, districtName)."""
    return [{'countyCode': cc, 'countyName': cn, 'districtCode': dc,
             'districtName': dn} for cc, cn, dc, dn in rows]


REFERENCE = ref(
    ('1', 'APPLING', '1', 'STATE'),
    ('1', 'APPLING', '2', 'SCHOOL'),
    ('1', 'APPLING', '3', 'COUNTY INCORPORATED'),
    ('1', 'APPLING', '5', 'BAXLEY'),
    ('1', 'APPLING', '15', 'COUNTY UNINCORPORATED'),
    ('1', 'APPLING', '20', 'COUNTY FIRE DIST'),
    # Bartow files its TADs with the county-name prefix in the reference year,
    # which is exactly the drift normalisation has to absorb.
    ('8', 'BARTOW', '2', 'Bartow County - School'),
    ('8', 'BARTOW', '90', 'Bartow County - TAD - E MAIN'),
)


print('Row extraction')
rows = P.rows_from_text(TEXT)
check(len(rows) > 40, 'the fixture yields %d data rows' % len(rows))
check(all(len(r) == 4 for r in rows), 'each row is (county, district, m&o, bond)')
check(not any(r[0] in ('County', 'GEORGIA', 'Local', 'PTS-R006-OD') for r in rows),
      'header and running-title lines are not mistaken for data')
no_rate = [r for r in rows if r[2] is None]
check(no_rate, 'rows with NO millage at all are extracted, not skipped: %d found '
               '(e.g. %s %s)' % (len(no_rate), no_rate[0][0], no_rate[0][1]))
check(any(r[2] is not None for r in rows), 'and rows with a rate are extracted')
check(raises(lambda: P.rows_from_text('nothing here\njust prose\n'), 'no data rows'),
      'text with no data rows refuses rather than returning an empty year')

print('\nThe name -> code index')
idx = P.code_index(REFERENCE)
check(idx[('APPLING', 'SCHOOL')] == ('1', '2'), 'an exact name resolves to its codes')
check(idx[('BARTOW', 'SCHOOL')] == ('8', '2'),
      "the reference year's '<County> County - ' prefix is normalised away, so "
      "2019's bare 'SCHOOL' still resolves")
ambiguous = P.code_index(REFERENCE + ref(('1', 'APPLING', '99', 'SCHOOL')))
check(('APPLING', 'SCHOOL') not in ambiguous,
      'a name mapping to TWO district codes is excluded from the index, not guessed')
check(('APPLING', 'BAXLEY') in ambiguous,
      'and the other names in that county still resolve')

print('\nParsing with borrowed codes')
recs, unresolved = P.parse_text(TEXT, REFERENCE, year=2019)
check(recs, 'records were produced')
check(all(r['taxYear'] == 2019 for r in recs), 'every record is tax year 2019')
by = {(r['countyName'], r['districtName']): r for r in recs}
school = by[('APPLING', 'SCHOOL')]
check(school['countyCode'] == '1' and school['districtCode'] == '2',
      "Appling's 2019 school line borrows the reference year's codes (1, 2)")
check(school['millageMO'] == 14.102,
      'and keeps its own 2019 rate, 14.102 — not the reference year\'s: %r'
      % school['millageMO'])
check(school['districtType'] == 'school', 'districtType is derived as usual')
check(school['occurrence'] == 1, 'occurrence is 1')

print('\n2019 has no tax and no assessed value, and says so')
check(school['dataSource'] == P.DATA_SOURCE == 'millage-pdf',
      'every record is tagged millage-pdf')
check(school['totalTaxMO'] is None and school['assessedValueMO'] is None,
      'tax and assessed value are null, because the source has no such columns')
check(P.REFERENCE_YEAR == 2020,
      'the reference year is the ADJACENT workbook year (2020), where name drift '
      'is lowest — not something further away')

print('\nUnresolvable rows are dropped and reported, never invented')
check(unresolved, '%d row(s) did not resolve against this minimal reference'
                  % len(unresolved))
check(all(isinstance(u, tuple) and len(u) == 2 for u in unresolved),
      'each is (county, district) so the caller can print it')
names = {(c, d) for c, d in unresolved}
check(('HENRY', 'COUNTY INC - MCDONOUGH') in names,
      "Henry's per-city incorporated rows are among them — a real 2019-only "
      'district, not a matching failure')
resolved_keys = {(r['countyCode'], r['districtCode']) for r in recs}
check(len(resolved_keys) == len(recs),
      'no two kept records share a (countyCode, districtCode), so the published '
      'key stays unique')
check(not any(r['districtCode'].startswith(('pdf', 'x', '?')) for r in recs),
      'no record carries a synthetic district code')

print('\nA scanned or Type 3 year refuses')
# Handed a file that is not a PDF, pdf_text must RAISE MillagePdfError — either
# because poppler rejects it, or (in CI, which has no poppler) because poppler is
# absent. Both are refusals, so this is meaningful with or without it installed.
try:
    P.pdf_text(FIXTURE)
    check(False, 'pdf_text accepted a non-PDF file')
except P.MillagePdfError as exc:
    check(True, 'pdf_text refuses a non-PDF with MillagePdfError: %s'
                % str(exc)[:60])
except Exception as exc:                          # noqa: BLE001
    check(False, 'pdf_text raised %s instead of MillagePdfError: %s'
                 % (type(exc).__name__, str(exc)[:60]))
check('scanned' in P.pdf_text.__doc__ or 'no usable text' in P.pdf_text.__doc__,
      'and its contract is to refuse a file with no usable text')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll 2019 millage-PDF invariants hold.')
