#!/usr/bin/env python3
"""Turn the statewide millage dataset into what one /local/<slug>/ page shows.

Phase 1b of docs/LOCAL-EXPANSION-SCOPE.md. The input is ga-millage.json as
generate_ga_millage.py writes it (phase 1a); the output is a small per-place view
that build_millage_places.py bakes into a site-only file and
_includes/entity/place.html renders SERVER-SIDE. Server-rendered, not fetched,
because property tax is the highest-search-intent topic in the /local/ section
and the table is a few hundred bytes per place — the same reasoning that keeps
the officials section server-rendered while meetings load client-side.

WHICH LEVIES APPLY TO A RESIDENT
--------------------------------
A Georgia property owner pays several jurisdictions at once, and which ones
depends on whether the property sits inside a city:

  * COUNTY place   -> the county's unincorporated rate (what an owner outside any
                      city pays), the county school system, and the state line.
  * CITY place     -> the county's INCORPORATED rate, the county school system,
                      the state line, and the city's own rate. A city inside a
                      city school district pays that instead of the county's.

So a county page and a city page inside it legitimately show different county
rates. That is the single most confusing thing about Georgia property tax and the
reason the rows are labelled rather than just listed.

THE COMBINED RATE IS DERIVED, SO IT IS CONSERVATIVE
---------------------------------------------------
`combined` is the sum of the applicable lines, and it is emitted for a year ONLY
if every applicable line reports a rate for that year. A missing component makes
the sum wrong rather than approximate, and this is a claim about someone's bill
(see the standing caution in the scope doc). It also excludes every special
district — fire, TAD, CID, BID, SSD, hospital, library, recreation — because
whether one applies depends on the parcel, not the city. The page says so.

JOINS
-----
Place -> DOR county by CANONICAL county name, never by the per-year name: DOR
abbreviates names per row, giving 191 distinct names for 159 codes (see
dor_digest.canonical_county_names). A consolidated place carries both names
("Augusta-Richmond County"), so the county is the segment after the hyphen.

City -> district row by TYPE PLUS EXACT NORMALISED NAME, never by substring.
'ATLANTA' as a substring also matches 'IND SCHOOL ATLANTA', 'TAD - ATLANTA
BELTLINE' and 'CID ATLANTA/MIDTOWN 05C'; 'CARROLLTON' also matches
'COUNTY INC - CARROLLTON'. Fort Oglethorpe is the case that forces the
normalisation: its only row is named 'CATOOSA COUNTY - FORT OGLETHORPE'.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import dor_digest as D  # noqa: E402

# The county line a resident pays, most specific first. A CONSOLIDATED
# government has no incorporated/unincorporated split, so it falls through:
# Macon-Bibb and Athens-Clarke publish only an incorporated line, Columbus-
# Muscogee only a countywide one. Echols County has no incorporated municipality
# at all, so it has no incorporated line. Verified across 2020-2025: 3 counties
# lack county_unincorporated and 2 lack county_incorporated, so both chains must
# be able to fall back to countywide.
COUNTY_CHAIN = ('county_unincorporated', 'county_incorporated', 'countywide')
CITY_CHAIN = ('county_incorporated', 'countywide')

# THE STATE LINE IS DELIBERATELY NOT A COMPONENT. Georgia's state property tax is
# gone: across all 953 state rows in 2020-2025 every one that reports a rate
# reports 0.0 — not one is non-zero — while 126 report nothing at all. Summing it
# would add zero and, worse, those 126 blanks would void the combined rate for
# whole county-years under the all-components-present rule. Carrollton 2025 is
# exactly that case. The page states the state rate is zero instead.
STATE_IS_ZERO = True

LABELS = {
    'county_unincorporated': 'County (unincorporated)',
    'county_incorporated': 'County (inside a city)',
    'school': 'County school district',
    'city_school': 'City school district',
    'state': 'State',
    'countywide': 'Countywide total',
    'county_service_district': 'County service district',
    'city': 'City',
    'fire': 'Fire district',
    'tad': 'Tax allocation district',
    'cid': 'Community improvement district',
    'bid': 'Business improvement district',
    'ssd': 'Special service district',
    'hospital': 'Hospital',
    'library': 'Library',
    'recreation': 'Recreation',
    'development_authority': 'Development authority',
    'unclassified': 'Other',
}


DASH = '\u2013'  # en dash: this year has no rate, which is not the same as zero


def fmt(v):
    """A millage figure as the page shows it: three decimals, or an en dash."""
    return DASH if v is None else '%.3f' % v


class MillageError(Exception):
    """A join could not be made. Raised so a silent empty section is impossible."""


def load(path):
    """Read ga-millage.json's columnar form back into dicts."""
    with open(path, encoding='utf-8') as fh:
        blob = json.load(fh)
    fields = blob['metadata']['fields']
    return [dict(zip(fields, row)) for row in blob['rows']], blob['metadata']


def county_key(place):
    """The canonical DOR county name for a place, or None for a city.

    'Appling County' -> 'APPLING'. A consolidated government carries the city and
    the county ('Augusta-Richmond County', 'Macon-Bibb County'), and DOR files it
    under the county, which is the segment after the hyphen.
    """
    if (place.get('type') or '') == 'city':
        return None
    name = re.sub(r'\s+', ' ', (place.get('name') or '')).strip().upper()
    name = re.sub(r'\s+COUNTY$', '', name)
    if '-' in name:
        name = name.rsplit('-', 1)[1].strip()
    return name or None


def city_key(place):
    """The normalised district name a city place should match on."""
    name = re.sub(r'\s+', ' ', (place.get('name') or '')).strip().upper()
    return re.sub(r'^CITY OF\s+', '', name).strip()


def _norm(rec):
    """A record's district name, county prefix stripped, for matching only."""
    return D.normalize_district_name(rec.get('districtName'),
                                    rec.get('countyName'))


def _series(recs):
    """{year: millage} for one district, M&O only, blanks omitted."""
    out = {}
    for r in recs:
        if r.get('millageMO') is None:
            continue
        out[int(r['taxYear'])] = r['millageMO']
    return out


def _pick_group(recs, prefer=None):
    """One district's rows out of a type that may hold several districts.

    A county can levy its general rate through SEVERAL districts of the same
    kind — Carroll files 'COUNTY INC - CARROLLTON', '- BREMEN' and '- OTHER';
    Fayette has five. Treating them as one series silently blends different
    cities' rates into the figure a resident is told they pay, which is how
    Carrollton's page first showed Carroll's 'OTHER' rate.

    So: group by district code, then prefer (1) the group naming `prefer` (the
    city whose page this is), (2) the generic line — an exact
    'COUNTY INCORPORATED'/'COUNTY UNINCORPORATED', or failing that one naming
    'OTHER' — and (3) the lowest district code, so the choice is deterministic.
    """
    groups = {}
    for r in recs:
        groups.setdefault(r.get('districtCode'), []).append(r)
    if len(groups) == 1:
        return next(iter(groups.values()))

    if prefer:
        for code, grp in groups.items():
            if prefer in _norm(grp[-1]):
                return grp
    generic = ('COUNTY INCORPORATED', 'COUNTY UNINCORPORATED', 'COUNTYWIDE',
               'COUNTY WIDE', 'SCHOOL')
    for code, grp in groups.items():
        if _norm(grp[-1]) in generic:
            return grp
    for code, grp in groups.items():
        if 'OTHER' in _norm(grp[-1]):
            return grp
    return groups[sorted(groups, key=lambda c: int(c or 0))[0]]


def _line(label, kind, recs):
    code = recs[0].get('districtCode')
    return {
        'label': label,
        'type': kind,
        'districtCode': code,
        'districtName': recs[-1].get('districtName'),
        'byYear': _series(recs),
    }


def place_view(rows, place, places_by_slug):
    """The millage view for one place, or None when nothing joins.

    `rows` is the whole statewide dataset; `place` a places.yml entry;
    `places_by_slug` the registry, needed to reach a city's parent county.
    """
    ptype = place.get('type') or 'county'
    if ptype == 'city':
        parent = places_by_slug.get(place.get('parentCounty') or '')
        if not parent:
            raise MillageError('%s: city with no parentCounty in places.yml'
                               % place.get('slug'))
        ckey = county_key(parent)
    else:
        ckey = county_key(place)
    if not ckey:
        return None

    mine = [r for r in rows if (r.get('countyName') or '').upper() == ckey]
    if not mine:
        return None

    by_type = {}
    for r in mine:
        by_type.setdefault(r.get('districtType'), []).append(r)

    lines = []

    if ptype == 'city':
        want = city_key(place)
        city_rows = _pick_group([r for r in by_type.get('city', []) if _norm(r) == want]) \
            if any(_norm(r) == want for r in by_type.get('city', [])) else []
        # A city school district replaces the county system for that city's
        # residents, so look for one named after this city.
        _cs = [r for r in by_type.get('city_school', []) if want in _norm(r)]
        cs_rows = _pick_group(_cs) if _cs else []
    else:
        city_rows, cs_rows = [], []

    # The county line, by fallback chain, labelled for whichever rung answered.
    # On a city page the county's per-city variant wins, when it files one.
    prefer = city_key(place) if ptype == 'city' else None
    for kind in (CITY_CHAIN if ptype == 'city' else COUNTY_CHAIN):
        recs = by_type.get(kind) or []
        if recs:
            lines.append(_line(LABELS[kind], kind, _pick_group(recs, prefer)))
            break

    # The county school system, unless a city system stands in for it.
    if not cs_rows:
        recs = by_type.get('school') or []
        if recs:
            lines.append(_line(LABELS['school'], 'school', _pick_group(recs)))

    if cs_rows:
        lines.append(_line('%s city school district' % city_key(place).title(),
                           'city_school', cs_rows))
    if city_rows:
        lines.append(_line('City of %s' % city_key(place).title(), 'city', city_rows))

    if not lines:
        return None

    years = sorted({int(r['taxYear']) for r in mine})

    # Year-aligned arrays alongside the byYear maps. Liquid has no clean way to
    # look a hash up by a number, so the template iterates these instead and a
    # missing year is an explicit null in the right column.
    #
    # `*Text` holds the already-formatted figure. Millage is quoted to three
    # decimals by convention, and Liquid has no number formatting — left to it,
    # a column reads "12.916, 16.0, 15.75", which looks like sloppy arithmetic
    # on a page about someone's tax bill. An en dash marks a year with no rate.
    for ln in lines:
        ln['values'] = [ln['byYear'].get(y) for y in years]
        ln['valuesText'] = [fmt(v) for v in ln['values']]

    # Conservative combined: only where EVERY line reports that year.
    combined = {}
    for y in years:
        vals = [ln['byYear'].get(y) for ln in lines]
        if all(v is not None for v in vals):
            combined[y] = round(sum(vals), 3)

    # Say WHY a combined rate is absent rather than printing a bare dash. The
    # honest case is Columbus-Muscogee: its county levy is split across urban,
    # rural and Fort Benning service districts at different rates, so which one a
    # resident pays depends on the parcel and there is no single county figure to
    # add. Inventing one would be a wrong claim about a tax bill.
    combined_note = None
    if len(combined) < len(years):
        thin = [ln['label'] for ln in lines
                if any(ln['byYear'].get(y) is None for y in years)]
        if not combined:
            combined_note = ('No combined rate is shown: %s reports no rate for '
                             'these years, so there is nothing to add it to.'
                             % (thin[0] if thin else 'a component'))
        else:
            combined_note = ('A combined rate is shown only for years where every '
                             'line below reports one.')

    # Everything else in the county, so the page can offer the full picture
    # without implying a resident pays it.
    shown = {(ln['type'], ln['districtCode']) for ln in lines}
    other = []
    for kind, recs in sorted(by_type.items()):
        groups = {}
        for r in recs:
            groups.setdefault(r.get('districtCode'), []).append(r)
        for code, grp in sorted(groups.items(), key=lambda kv: int(kv[0] or 0)):
            if (kind, code) in shown:
                continue
            s = _series(grp)
            if not s:
                continue
            other.append({
                'label': grp[-1].get('districtName'),
                'type': kind,
                'typeLabel': LABELS.get(kind, 'Other'),
                'districtCode': code,
                'byYear': s,
                'values': [s.get(y) for y in years],
                'valuesText': [fmt(s.get(y)) for y in years],
            })

    return {
        'stateRateIsZero': STATE_IS_ZERO,
        'countyName': ckey.title(),
        'countyCode': mine[0].get('countyCode'),
        'placeType': ptype,
        'years': years,
        'lines': lines,
        'combined': combined,
        'combinedValues': [combined.get(y) for y in years],
        'combinedValuesText': [fmt(combined.get(y)) for y in years],
        'latestCombinedText': fmt(combined.get(years[-1])) if years else DASH,
        'combinedNote': combined_note,
        'latestYear': years[-1] if years else None,
        'latestCombined': combined.get(years[-1]) if years else None,
        'other': other,
    }
