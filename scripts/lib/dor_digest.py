#!/usr/bin/env python3
"""Georgia DOR "Tax Digest Consolidated Summaries" -> tidy millage records.

SOURCE
------
https://dor.georgia.gov/local-government-services/digest-compliance/digest-consolidated-summaries
One workbook per tax year, 2020 onward. Served with a .xls extension but they are
real OOXML, so lib/xlsx.py reads them directly (do NOT rename-and-trust: the
reader goes by content).

Each workbook is ONE flat sheet, ~1,800 rows x 425 columns, one row per
(county x tax district). Columns 1-5 identify the row; 6-419 are parcels, acreage
and assessed value per property class plus the state (S*) and local (L1-L9)
homestead exemptions; the last six are the totals and the levy:

    Total Assessed Value-M&O | Total Assessed Value-Bond
    Millage Rate-M&O         | Millage Rate-Bond
    Total Tax-M&O            | Total Tax-Bond

This module publishes "table A" only — identity plus levy. The exemption columns
are deliberately left for a separate table (see docs/LOCAL-EXPANSION-SCOPE.md
section 4.2, the HB 581 work); folding 400 exemption columns into the millage
series would make the published file unusable for the page that needs it.

WHY THIS BEATS THE MILLAGE PDFs
-------------------------------
The "County Ad Valorem Tax Digest Millage Rates" PDFs (PTS-R006-OD) carry the
same rates but 2021 and 2024 are scanned images, and 2025 uses a Type 3 font with
no ToUnicode so pdftotext emits mojibake. Spot-checked and the two sources agree
exactly (2023 Appling: SCHOOL 12.243, COUNTY INCORPORATED 11.924, BAXLEY 4.896,
COUNTY FIRE DIST 0.470). The workbooks also carry Total Tax in dollars, which the
PDFs do not. The PDFs remain useful only for 2019, which predates the workbooks.

THE FIVE RULES THIS FILE EXISTS TO ENFORCE
------------------------------------------
1. KEY ON CODES, NEVER ON NAMES. (County Code, District Code, Tax Year) is
   stable: 1,768 of ~1,800 pairs appear in both 2023 and 2025. District Name is
   not — 274 pairs (15%) share a code but carry a different name, and the drift
   is not a consistent transform. Only 2 of those 274 differ by a clean
   "<County> - " prefix, and it moves in BOTH directions: Appling's school line is
   "SCHOOL" in 2023 and "Appling County - SCHOOL" in 2025, while Newton's is
   "Newton County - Newton School" in 2023 and "SCHOOL" in 2025. Casing and
   wording drift too (COUNTY WIDE LIBRARY -> Countywide Library). A name-based
   join silently fragments 15% of the series into false new districts.

2. DISTRICT CODES ARE ONLY MEANINGFUL FOR 0-3. Verified across all 159 counties
   in 2025: code 1 is STATE (158 rows, zero off-pattern), code 2 is the county
   SCHOOL system (158 rows, zero off-pattern), code 3 is COUNTY INCORPORATED
   (154 rows). Above that they are per-county arbitrary — code 15 is
   COUNTY UNINCORPORATED in 24 counties and a city (HARALSON, GILLSVILLE, CARL)
   in others, with 100 distinct names. So 0-3 classify by CODE and everything
   else classifies by NAME.

3. CITY SCHOOL SYSTEMS ARE NAME-ONLY. The 21 independent city systems appear on
   district codes 7, 17, 27, 30, 37, 47, 55, 57, 67 and 75 — no pattern — under
   several spellings: "IND SCHOOL <CITY>" (most), "CARROLLTON CITY SCHOOLS",
   "BREMEN SCHOOLS", and "IND SCHOOL DECATUR 50%" (a partial levy; the "50%" is
   data, do not strip it). They cross-check _data/school_districts.yml, and like
   the PDF the workbook lists a system under EACH county it serves — Atlanta
   appears under both Fulton and DeKalb at 20.5 mills.

4. THE KEY IS ALMOST UNIQUE, AND THE EXCEPTION IS REAL. Across 2020-2025,
   exactly one (county, district, year) appears twice: Cherokee 2022 district 18,
   'HOLLY SPRINGS FIRE', listed once at 898,991,358 assessed / 2,682,590.21 tax
   and once at 8,264,691 / 24,661.84, both at 2.984 mills. Summing them would be
   inventing a tax figure, and dropping one would lose money, so both rows are
   published with an `occurrence` ordinal (1, 2, ...) that makes the identity
   unique and the anomaly visible. `key()` includes it. Every other row in six
   years has occurrence 1.

5. CODE 0 IS NOT ALWAYS EMPTY. Every county has a code-0 countywide roll-up row
   (159 of them in 2025) and the millage is usually blank — but 2 counties carry
   a rate there. So the row is kept and classified, never dropped on the
   assumption that it is a header.

6. NUMBERS STAY AS TEXT UNTIL ASKED FOR. The workbook stores float artifacts
   ("7414236.4699999997"), so values are read as strings and converted once, on
   request, with explicit rounding. Reading them as floats and re-serialising is
   how 11.273 becomes 11.272999999999999 in a published file.

Run the invariants: python scripts/test_dor_digest.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import xlsx  # noqa: E402

# Columns located by HEADER TEXT, never by position — the same rule the meeting
# adapters follow. A workbook that renames or drops one of these fails loudly in
# parse(); it does not publish a column of blanks.
REQUIRED = {
    'county_name':   'County Name',
    'county_code':   'County Code',
    'district_name': 'District Name',
    'district_code': 'District Code',
    'tax_year':      'Tax Year',
    'assessed_mo':   'Total Assessed Value-M&O',
    'assessed_bond': 'Total Assessed Value-Bond',
    'millage_mo':    'Millage Rate-M&O',
    'millage_bond':  'Millage Rate-Bond',
    'tax_mo':        'Total Tax-M&O',
    'tax_bond':      'Total Tax-Bond',
}

# Rule 2: these district codes mean the same thing in every county.
CODE_TYPES = {
    '0': 'countywide',
    '1': 'state',
    '2': 'school',
    '3': 'county_incorporated',
}

# Rule 3 + the rest of rule 2: everything else is classified from the NORMALIZED
# name, most specific first. Ordering matters — "IND SCHOOL DECATUR" must be seen
# as a city school before any generic SCHOOL rule could claim it.
NAME_TYPES = (
    ('city_school',           re.compile(r'\bIND\b.*\bSCHOOL|\bSCHOOLS?\b.*\bCITY\b|\bCITY\b.*\bSCHOOLS?\b|^\w+ SCHOOLS$')),
    # A county URBAN/RURAL SERVICE DISTRICT is the county's own levy on part of
    # its territory, not a city. Columbus-Muscogee is the case that matters: the
    # consolidated government's countywide row carries NO rate, and its actual
    # levy sits in 'COUNTY USD 1 - URBAN', 'COUNTY USD 2 - RURAL' and
    # 'COUNTY USD 4 - FTBENNING'. Classified as a city, those became phantom
    # municipalities and Muscogee showed no county rate at all.
    ('county_service_district',
                              re.compile(r'COUNTY\s+USD\b|\bUSD\s*\d|URBAN\s+SVC|URBAN\s+SERVICE')),

    # ---- SPECIAL-PURPOSE DISTRICTS COME FIRST, BEFORE THE COUNTY PATTERNS ----
    # Several special districts carry 'COUNTY' or 'UNINCORPORATED' in their name:
    # 'COUNTY UNINC FIRE DISTRICT' (Hall), 'SSD UNINCORPORATED' (Henry),
    # 'COUNTY UNINC DEVELOPMENT SVC' (Hall). Matched after the county rules they
    # would be read as the county's own general levy and blended into the rate a
    # resident is told they pay. What a district IS beats where it applies.
    ('fire',                  re.compile(r'\bFIRE\b')),
    ('ssd',                   re.compile(r'\bSSD\b')),
    ('tad',                   re.compile(r'\bTAD\b')),
    ('cid',                   re.compile(r'\bCID\b')),
    ('bid',                   re.compile(r'\bBID\b')),
    ('hospital',              re.compile(r'\bHOSPITAL\b')),
    ('library',               re.compile(r'\bLIBRAR')),
    ('recreation',            re.compile(r'\bRECREATION\b')),
    ('development_authority', re.compile(r'\bDEV(ELOPMENT)?\s+AUTH|\bECON(OMIC)?\s+DEV|\bDEVELOPMENT\s+SVC')),

    # ---- THEN the county's own general levies ----
    # 'UNINCORPORATED' on its own, once the '<County> County - ' prefix is gone.
    # Barrow files its unincorporated levy as 'Barrow County - UnIncorporated',
    # which the COUNTY-prefixed pattern alone does not catch.
    ('county_unincorporated', re.compile(r'COUNTY\s+UNINC|\bUNINCORPORAT')),
    ('county_incorporated',   re.compile(r'COUNTY\s+INC\b|COUNTY\s+INCORPORAT')),
    ('countywide',            re.compile(r'^COUNTY\s*WIDE$|^COUNTYWIDE$')),
)


class DigestError(Exception):
    """The workbook is not the shape we parse. Raised, never swallowed."""


def normalize_district_name(name, county_name):
    """Uppercase, whitespace-collapsed name with a '<County> County - ' prefix removed.

    Only for CLASSIFYING and for cross-checking across years — never for joining
    (rule 1) and never as the published label. The prefix is stripped because the
    same district carries it in one year and not the next.
    """
    s = re.sub(r'\s+', ' ', (name or '')).strip()
    c = re.sub(r'\s+', ' ', (county_name or '')).strip()
    if c:
        # "Appling County - SCHOOL", "APPLING COUNTY - SCHOOL", "Murray County - Murray County"
        s = re.sub(r'^' + re.escape(c) + r'\s+COUNTY\s*-\s*', '', s, flags=re.I).strip()
    return s.upper()


def district_type(district_code, normalized_name):
    """Classify a district. Returns a type string, or 'unclassified'.

    Codes 0-3 win because they are verified stable statewide; everything else is
    matched on the normalized name. An unmatched row is reported as
    'unclassified' rather than guessed into a bucket, so a new kind of district
    surfaces in the generator's summary instead of hiding inside 'city'.
    """
    code = (district_code or '').strip()
    if code in CODE_TYPES:
        # A city school can sit on a low code in principle; name beats code only
        # for the school case, where misfiling a city system as the county
        # system would double-count a district on the place page.
        if code != '2' and NAME_TYPES[0][1].search(normalized_name or ''):
            return 'city_school'
        return CODE_TYPES[code]
    name = normalized_name or ''
    for kind, rx in NAME_TYPES:
        if rx.search(name):
            return kind
    return 'city' if name else 'unclassified'


def to_number(raw, places):
    """'10.943' -> 10.943 ; '' -> None ; '7414236.4699999997' -> 7414236.47.

    Rounds explicitly (rule 5). Returns None for a blank so a missing levy stays
    distinguishable from a real zero — a county that genuinely levies 0 mills and
    one that reported nothing are different facts.
    """
    s = (raw or '').strip().replace(',', '')
    if not s:
        return None
    try:
        return round(float(s), places)
    except ValueError:
        raise DigestError('not a number: %r' % (raw,))


def parse(path, sheet_name=None):
    """Read one workbook into a list of tidy dicts, one per county x district.

    Raises DigestError if a required column is missing (a layout change), if the
    sheet is empty, or if a row carries an unparseable number.
    """
    it = xlsx.padded_rows(path, sheet_name)
    try:
        header = next(it)
    except StopIteration:
        raise DigestError('%s: sheet is empty' % os.path.basename(path))

    pos = {}
    seen = {h.strip(): i for i, h in enumerate(header) if h and h.strip()}
    missing = []
    for key, label in REQUIRED.items():
        if label in seen:
            pos[key] = seen[label]
        else:
            missing.append(label)
    if missing:
        raise DigestError('%s: layout has changed — missing column(s): %s'
                          % (os.path.basename(path), ', '.join(sorted(missing))))

    out = []
    for raw in it:
        def cell(key):
            i = pos[key]
            return (raw[i] if i < len(raw) else '') or ''

        county_name = cell('county_name').strip()
        county_code = cell('county_code').strip()
        district_code = cell('district_code').strip()
        if not county_code or not district_code:
            continue  # a spacer or footer row, not a district
        district_name = cell('district_name').strip()
        norm = normalize_district_name(district_name, county_name)
        out.append({
            'taxYear': int(cell('tax_year').strip() or 0) or None,
            'countyCode': county_code,
            'countyName': county_name,
            'districtCode': district_code,
            'districtName': district_name,
            'districtType': district_type(district_code, norm),
            'millageMO': to_number(cell('millage_mo'), 3),
            'millageBond': to_number(cell('millage_bond'), 3),
            'totalTaxMO': to_number(cell('tax_mo'), 2),
            'totalTaxBond': to_number(cell('tax_bond'), 2),
            'assessedValueMO': to_number(cell('assessed_mo'), 0),
            'assessedValueBond': to_number(cell('assessed_bond'), 0),
        })

    if not out:
        raise DigestError('%s: no district rows found' % os.path.basename(path))

    # Rule 4: number repeats of the same (county, district, year) rather than
    # merging or dropping them. Counted in document order so the ordinal is
    # stable across runs of the same workbook.
    seen_keys = {}
    for rec in out:
        k = (rec['countyCode'], rec['districtCode'], rec['taxYear'])
        seen_keys[k] = seen_keys.get(k, 0) + 1
        rec['occurrence'] = seen_keys[k]
    return out


def key(rec):
    """The stable, unique identity of a record (rules 1 and 4)."""
    return (rec['countyCode'], rec['districtCode'], rec['taxYear'],
            rec.get('occurrence', 1))


def canonical_county_names(recs):
    """{countyCode: canonical name} — the modal name, longest wins a tie.

    WHY: DOR's own county names are not clean. 26 of the 159 county codes carry a
    truncated or suffixed name in at least one year — code 2 is 'ATKINSON' in
    2020-2025 but also 'ATKINS' in 2023-2025 and 'ATKINS SO' in 2024; code 32 is
    'CLINCH', 'CLINCH COUNTY' and 'CLINCH COUNTY TAX'; others carry two-letter
    tails ('HEARD KA', 'JONES SO', 'GREENE NW', 'CHARLT TB') that look like an
    internal DOR marker. The truncation is per-ROW, not per-year: a single year
    can hold both spellings for the same county.

    Across the full 2020-2025 dataset that produces 191 distinct county names for
    159 codes, so countyName is unusable as a join key or a display label. The
    code is the identity; this gives the one name to show for it.

    Needs the WHOLE dataset, so it is applied by the generator after every
    workbook is read, not inside parse().
    """
    counts = {}
    for r in recs:
        cc = r.get('countyCode')
        name = (r.get('countyName') or '').strip()
        if not cc or not name:
            continue
        counts.setdefault(cc, {})
        counts[cc][name] = counts[cc].get(name, 0) + 1
    out = {}
    for cc, names in counts.items():
        # Most rows wins; a tie goes to the longest name, which is the unabbreviated
        # one in every observed case. Alphabetical last, so the result is stable.
        out[cc] = sorted(names.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]
    return out


def duplicate_groups(recs):
    """[(countyName, districtCode, taxYear, [rec, ...]), ...] for repeated keys.

    Reported by the generator so a source defect is visible in the run output
    instead of being quietly averaged away.
    """
    groups = {}
    for r in recs:
        groups.setdefault((r['countyCode'], r['districtCode'], r['taxYear']), []).append(r)
    return [(v[0]['countyName'], dc, yr, v)
            for (cc, dc, yr), v in sorted(groups.items()) if len(v) > 1]
