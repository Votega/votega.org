#!/usr/bin/env python3
"""Generate county public-meeting data from CivicPlus Agenda Centers.

Reads the county registry (_data/county_civicplus.yml) and, for each CivicPlus
county, writes assets/data/county-<slug>-meetings.json:

    {
      "metadata": { generatedAt, source, sourceUrl, county, fips, count },
      "bodies":   [ "Board of Commissioners", ... ],   # panels present on the site
      "meetings": [ { body, date, id, title, agendaUrl, minutesUrl,
                      videoUrl, hasPreviousVersions }, ... ]
    }

Only meeting *links* are stored — never the agenda/minutes PDFs themselves — so
the committed JSON stays small (the git-history concern in CLAUDE.md's scaling
notes). The files live on the county server; this is an index over them.

Usage:
    python scripts/generate_county_meetings.py [--slug newton] [--registry PATH]

Exits non-zero if a county's Agenda Center cannot be fetched or parses to zero
meetings — refusing to overwrite good data with nothing. Other counties in the
run still succeed; the failure is reported at the end.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.civicplus import fetch_agenda_center  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REGISTRY = os.path.join(ROOT, '_data', 'county_civicplus.yml')
OUT_DIR = os.path.join(ROOT, 'assets', 'data')


def load_registry(path):
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('counties', []) if data else []


def build_county(county):
    """Fetch + normalize one county. Returns the output dict, or None on failure."""
    slug = county['slug']
    base_url = county['base_url'].rstrip('/')
    module_id = county.get('agenda_module_id', 65)

    print('Fetching %s Agenda Center (%s)...' % (county['name'], base_url))
    meetings, bodies_seen = fetch_agenda_center(base_url, module_id=module_id)

    if meetings is None:
        print('  ERROR: could not fetch Agenda Center for %s' % slug)
        return None
    if not meetings:
        print('  ERROR: parsed zero meetings for %s (site markup may have changed)'
              % slug)
        return None

    with_minutes = sum(1 for m in meetings if m['minutesUrl'])
    print('  %d meeting(s) across %d body(ies); %d with minutes'
          % (len(meetings), len(bodies_seen), with_minutes))

    # Note any registry body that produced no panel — informational, not fatal
    # (a body with no posted meetings simply isn't rendered).
    expected = {_norm(b) for b in county.get('bodies', {})}
    present = {_norm(b) for b in bodies_seen}
    for missing in sorted(expected - present):
        print('  note: registry body not present on site: %s' % missing)

    return {
        'metadata': {
            'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': '%s, GA (CivicPlus Agenda Center)' % county['name'],
            'sourceUrl': '%s/AgendaCenter' % base_url,
            'county': county['name'],
            'fips': county.get('fips'),
            'count': len(meetings),
        },
        'bodies': bodies_seen,
        'meetings': meetings,
    }


def _norm(name):
    return ' '.join((name or '').lower().split())


def write_county(slug, payload):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'county-%s-meetings.json' % slug)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    print('  Wrote %s' % out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='only build this county (default: all in registry)')
    ap.add_argument('--registry', default=DEFAULT_REGISTRY)
    args = ap.parse_args()

    counties = load_registry(args.registry)
    if args.slug:
        counties = [c for c in counties if c['slug'] == args.slug]
        if not counties:
            sys.exit('No county with slug %r in %s' % (args.slug, args.registry))

    counties = [c for c in counties if c.get('platform') == 'civicplus']
    if not counties:
        sys.exit('No CivicPlus counties to build.')

    failed = []
    for county in counties:
        payload = build_county(county)
        if payload is None:
            failed.append(county['slug'])
            continue
        write_county(county['slug'], payload)

    if failed:
        sys.exit('FAILED: %s' % ', '.join(failed))
    print('Done.')


if __name__ == '__main__':
    main()
