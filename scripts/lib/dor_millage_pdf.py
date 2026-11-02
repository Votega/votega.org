#!/usr/bin/env python3
"""The 2019 DOR millage-rate PDF, parsed into digest-shaped records.

WHY ONLY 2019
-------------
DOR's machine-readable Tax Digest Consolidated Summaries (lib/dor_digest.py)
start at tax year 2020. One earlier year is available, and only one is worth
having: the "2019 Georgia County Ad Valorem Tax Digest Millage Rates" PDF
(PTS-R006-OD) has a clean Type 1 / WinAnsi text layer, so poppler reads it
exactly. Its siblings do not — 2021 and 2024 are scanned images, and 2025 uses a
Type 3 font with no ToUnicode that pdftotext renders as mojibake. So this module
is deliberately a single-year bridge, not a general PDF path.

THE HARD PART: THE PDF HAS NO CODES
-----------------------------------
The published dataset is keyed on (countyCode, districtCode, taxYear,
occurrence). The PDF carries NEITHER code — its table is just
`County | District | M&O | Bond`, by name. And matching districts across years by
name is the exact thing dor_digest's rule 1 forbids, because names drift for ~15%
of districts between 2023 and 2025.

So the codes are resolved by EXACT normalised name against an adjacent reference
year, and the match rate is measured rather than assumed. Against 2020 it is
**1,458 of 1,474 rows carrying a rate, 98.9%, with zero ambiguity** (no name maps
to two district codes). Adjacent-year drift is far lower than the two-year drift
that motivated rule 1, which is why this works at all — and why the reference
year must stay 2020 and not something further away.

A row whose name does not resolve is DROPPED, never given an invented code: an
unkeyed row cannot be joined, and a synthetic code would fork the series into a
phantom district. The 16 that drop are real 2019→2020 changes, not failures —
Henry's per-city `COUNTY INC - <CITY>` rows, Cherokee fire sub-districts, a
DeKalb annexation — and they are exotic sub-districts, not the county, school or
city lines a place page shows. The caller gets the count and the list.

WHAT 2019 DOES NOT HAVE
-----------------------
The PDF carries millage only. There is no tax levied, no assessed value, and no
countywide roll-up row (the XLSX synthesises one per county; 1,560 PDF rows + 159
of those + ~6 districts added in 2020 reconciles to 2020's 1,725).

Those fields are therefore null for 2019 — but `null` in this dataset means "the
jurisdiction reported none", which for 2019 would be a lie. So every record
carries `dataSource`, and 2019's is `millage-pdf`. A consumer summing tax by year
must filter on it.

A row with NO millage at all is kept, with a null rate: 86 of them, almost all
tax allocation districts that levy nothing, and the XLSX records those the same
way. Dropping them would misrepresent which districts existed.
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import dor_digest as D  # noqa: E402

DATA_SOURCE = 'millage-pdf'
REFERENCE_YEAR = 2020  # the nearest XLSX year; see the name-match note above

# An indented data row: county, district, then an optional M&O and Bond. The
# numbers are OPTIONAL because a district that levies nothing (a TAD, mostly)
# prints a name and no figures, and those rows are real.
_ROW = re.compile(
    r'^\s{6,}([A-Z][A-Z .\'&/-]*?)\s{2,}(\S.*?)'
    r'(?:\s{2,}(-?[\d,]+\.\d+)(?:\s+(-?[\d,]+\.\d+))?)?\s*$')

# Header and running-title fragments that match the row shape but are not data.
_NOT_A_COUNTY = {'County', 'GEORGIA', 'Local', 'PTS-R006-OD'}


class MillagePdfError(Exception):
    """The PDF is not the shape we parse. Raised, never swallowed."""


def pdf_text(path):
    """The PDF's text layer via poppler, or a clear error.

    Refuses a file with no usable text rather than returning nothing, which is
    how a scanned year (2021, 2024) would otherwise produce an empty dataset.
    """
    try:
        out = subprocess.run(['pdftotext', '-layout', path, '-'],
                             capture_output=True, timeout=120)
    except FileNotFoundError:
        raise MillagePdfError('pdftotext (poppler-utils) is not installed')
    except subprocess.TimeoutExpired:
        raise MillagePdfError('pdftotext timed out on %s' % os.path.basename(path))
    if out.returncode != 0:
        raise MillagePdfError('pdftotext failed on %s: %s'
                              % (os.path.basename(path),
                                 out.stderr.decode('utf-8', 'replace')[:200]))
    text = out.stdout.decode('utf-8', 'replace')
    if len(text.strip()) < 2000:
        raise MillagePdfError(
            '%s yielded almost no text (%d chars). A scanned or Type 3 year '
            'cannot be read this way — only 2019 has a clean text layer.'
            % (os.path.basename(path), len(text.strip())))
    return text


def rows_from_text(text):
    """[(county, district, millage_mo, millage_bond)] as written, strings or None."""
    out = []
    for line in text.splitlines():
        m = _ROW.match(line.rstrip())
        if not m:
            continue
        county = m.group(1).strip()
        if county in _NOT_A_COUNTY:
            continue
        district = re.sub(r'\s+', ' ', m.group(2)).strip()
        if not district:
            continue
        out.append((county, district, m.group(3), m.group(4)))
    if not out:
        raise MillagePdfError('no data rows found in the PDF text')
    return out


def code_index(reference_records):
    """{(COUNTY, NORMALISED DISTRICT): (countyCode, districtCode)} from an XLSX year.

    Built on the canonical county name per code, because DOR abbreviates county
    names per row. A name that maps to more than one district code is omitted
    entirely rather than guessed — an ambiguous key must not resolve.
    """
    canon = D.canonical_county_names(reference_records)
    seen = {}
    for r in reference_records:
        county = (canon.get(r['countyCode']) or r['countyName'] or '').upper()
        norm = D.normalize_district_name(r['districtName'], r['countyName'])
        seen.setdefault((county, norm), set()).add((r['countyCode'], r['districtCode']))
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def parse(path, reference_records, year=2019):
    """(records, unresolved) for the 2019 millage PDF at `path`."""
    return parse_text(pdf_text(path), reference_records, year=year)


def parse_text(text, reference_records, year=2019):
    """(records, unresolved) from already-extracted PDF text.

    Split out from parse() so the test suite can exercise the whole pipeline on a
    text fixture: scripts/test_*.py run in CI with no pip packages AND no
    poppler, so a test that shelled out to pdftotext could not run there.

    `records` are digest-shaped and keyed with codes borrowed from the reference
    year. `unresolved` is [(county, district)] for rows whose name did not
    resolve — returned, not swallowed, so the caller can report them.
    """
    index = code_index(reference_records)
    if not index:
        raise MillagePdfError('the reference year produced no name->code index')

    records, unresolved = [], []
    for county, district, mo, bond in rows_from_text(text):
        key = (county.upper(), re.sub(r'\s+', ' ', district).strip().upper())
        codes = index.get(key)
        if not codes:
            unresolved.append((county, district))
            continue
        county_code, district_code = codes
        norm = D.normalize_district_name(district, county)
        records.append({
            'taxYear': year,
            'countyCode': county_code,
            'countyName': county,
            'countyNameAsFiled': county,
            'districtCode': district_code,
            'districtName': district,
            'districtType': D.district_type(district_code, norm),
            'occurrence': 1,
            'millageMO': D.to_number(mo, 3),
            'millageBond': D.to_number(bond, 3),
            # Not in this source. Null here does NOT mean "reported none" —
            # that is what dataSource is for.
            'totalTaxMO': None,
            'totalTaxBond': None,
            'assessedValueMO': None,
            'assessedValueBond': None,
            'dataSource': DATA_SOURCE,
        })

    dupes = len(records) - len({(r['countyCode'], r['districtCode']) for r in records})
    if dupes:
        raise MillagePdfError(
            '%d row(s) resolved to a district code already used this year — the '
            'name->code index is not unique enough to key %d' % (dupes, year))
    return records, unresolved
