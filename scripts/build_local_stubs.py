#!/usr/bin/env python3
"""Build _data/local_stubs.json: every Georgia county and incorporated place, so the
/local/ hub can show a faint "We're working on it..." card for the ones VoteGA does
not cover yet.

Source: Georgia Civic Data's shared `places`, `place_counties` and `counties`
dimensions (https://georgiacivicdata.org, CC BY 4.0), fetched as CSV from its REST
API. No key. The mapping is the Census place -> county relationship with each
county's share of the place's 2025 population.

What is NOT stubbed (it already has a real card, or is not a separate place):
  * a city that has an entry in _data/places.yml (matched on letters only, so
    "Social Circle" finds `socialcircle` and "LaFayette" finds `lafayette`);
  * a consolidated city-county government (Athens-Clarke, Macon-Bibb, Columbus...):
    the county card IS that government;
  * a place Census no longer lists as active (dissolved / merged).

A city sits under its PRIMARY county (the one holding most of its people) and is
offered as a chip under every other county with a non-zero share. A county that
is hidden in places.yml is stubbed like any other not-yet-covered one: `hidden`
means "not ready", which is what the stub card says.

Every county is listed, covered or not, because a covered county still shows stub
cards for the cities in it that have no card of their own. The template decides
per county which kind of header to draw. A city's `id` is its Census place FIPS:
stubs have no URL, so nothing links to it and it can never collide with a real slug.

Run:  python scripts/build_local_stubs.py            (rewrites _data/local_stubs.json)
      python scripts/build_local_stubs.py --check    (exit 1 if the committed file differs)

`build_stubs` is pure (rows in, dict out) and is what scripts/test_build_local_stubs.py
exercises; `main` is the only code that touches the network or the disk.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.ga_county_fips import GA_COUNTY_FIPS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, '_data', 'local_stubs.json')
PLACES_YML = os.path.join(ROOT, '_data', 'places.yml')
API = 'https://georgiacivicdata.org/api/v1/dimensions'
SOURCE = 'Georgia Civic Data (georgiacivicdata.org, CC BY 4.0): places, place_counties, counties'

EXPECT_COUNTIES = 159
MIN_PLACES = 400            # 538 active today; far below this means a bad read


def letters(s):
    """Lowercase letters/digits only, after dropping a leading 'City of'."""
    s = re.sub(r'(?i)^city of\s+', '', s or '')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def build_stubs(places, place_counties, counties, registry_city_keys, now=None):
    """places / place_counties / counties: lists of CSV dict rows.
    registry_city_keys: set of letters() keys of cities already in places.yml.
    Returns (stubs_dict, unmatched_registry_keys)."""
    slug_by_fips = {v: k for k, v in GA_COUNTY_FIPS.items()}
    name_by_fips = {c['county_fips']: c['county_name'] for c in counties}
    by_county = {f: {'slug': slug_by_fips[f], 'name': name_by_fips[f], 'fips': f,
                     'cities': [], 'alsoCities': []} for f in name_by_fips}

    shares = {}
    for r in place_counties:
        shares.setdefault(r['place_fips'], []).append(r)

    matched = set()
    n_cities = 0
    for p in sorted(places, key=lambda r: r['place_name'].lower()):
        if p['active'] != 'true' or p['consolidated_county_fips']:
            continue
        key = letters(p['place_name'])
        if key in registry_city_keys:
            matched.add(key)
            continue
        rows = shares.get(p['place_fips']) or []
        primary = next((r['county_fips'] for r in rows if r['is_primary_county'] == 'true'),
                       p['county_fips'])
        if primary not in by_county:
            continue
        by_county[primary]['cities'].append({'id': p['place_fips'], 'name': p['place_name']})
        n_cities += 1
        for r in rows:
            f = r['county_fips']
            if f != primary and f in by_county and float(r['population_share']) > 0:
                by_county[f]['alsoCities'].append({'id': p['place_fips'], 'name': p['place_name'],
                                                   'primaryCounty': by_county[primary]['name']})

    out = sorted(by_county.values(), key=lambda c: c['name'].lower())
    for c in out:
        c['alsoCities'].sort(key=lambda x: x['name'].lower())
    now = now or datetime.now(timezone.utc)
    return ({
        'metadata': {
            'generatedAt': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': SOURCE,
            'count': len(out),
            'cityCount': n_cities,
        },
        'counties': out,
    }, registry_city_keys - matched)


def _fetch_csv(name, limit):
    from lib.http import fetch_bytes
    raw = fetch_bytes('%s/%s/rows?format=csv&limit=%d' % (API, name, limit),
                      headers={'User-Agent': 'votega.org build'}, label='gcd ' + name)
    if not raw:
        sys.exit('could not fetch the %s dimension' % name)
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))


def registry_city_keys():
    import yaml
    with open(PLACES_YML, encoding='utf-8') as f:
        places = yaml.safe_load(f)['places']
    return {letters(p['name']) for p in places if p['type'] == 'city'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if _data/local_stubs.json differs from a fresh build '
                         '(ignoring generatedAt)')
    args = ap.parse_args()

    places = _fetch_csv('places', 700)
    pcs = _fetch_csv('place_counties', 800)
    counties = _fetch_csv('counties', 200)
    if len(counties) != EXPECT_COUNTIES:
        sys.exit('counties dimension has %d rows, expected %d' % (len(counties), EXPECT_COUNTIES))
    if len(places) < MIN_PLACES:
        sys.exit('places dimension has only %d rows' % len(places))
    stubs, unmatched = build_stubs(places, pcs, counties, registry_city_keys())
    if unmatched:
        print('NOTE: places.yml cities with no match in the places dimension: %s'
              % ', '.join(sorted(unmatched)))
    if stubs['metadata']['cityCount'] < MIN_PLACES - 100:
        sys.exit('only %d city stubs - refusing to write' % stubs['metadata']['cityCount'])

    if args.check:
        try:
            with open(OUT, encoding='utf-8') as f:
                old = json.load(f)
        except (OSError, ValueError):
            sys.exit('%s missing or unreadable' % OUT)
        old['metadata'].pop('generatedAt', None)
        new = json.loads(json.dumps(stubs))
        new['metadata'].pop('generatedAt', None)
        if old != new:
            sys.exit('local_stubs.json is out of date - run scripts/build_local_stubs.py')
        print('local_stubs.json is current')
        return

    from lib.atomic_io import write_json_atomic
    write_json_atomic(OUT, stubs, indent=1)
    print('wrote %s: %d counties, %d city stubs' % (OUT, stubs['metadata']['count'],
                                                    stubs['metadata']['cityCount']))


if __name__ == '__main__':
    main()
