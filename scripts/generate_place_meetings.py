#!/usr/bin/env python3
"""Generate local-government public-meeting data from the places registry.

Reads _data/places.yml and, for each place that declares a `meetings` domain,
dispatches on the domain's `platform` to the matching adapter and writes
assets/data/local-<slug>-meetings.json:

    {
      "metadata": { generatedAt, source, sourceUrl, place, type, fips, count },
      "bodies":   [ "Board of Commissioners", ... ],
      "meetings": [ { body, date, id, title, agendaUrl, minutesUrl,
                      videoUrl, hasPreviousVersions }, ... ]
    }

The output schema is platform-agnostic: a CivicPlus Agenda Center and a CoreCode
PDF list both normalize to the shape above, so the /local/<slug>/ page never
knows which platform produced the data (see LOCAL-GOVERNMENT-IA.md). Only meeting
*links* are stored, never the PDFs — the committed JSON stays small.

Usage:
    python scripts/generate_place_meetings.py [--slug newton] [--registry PATH]

Exits non-zero if a place's meetings source cannot be fetched or parses to zero
meetings — refusing to overwrite good data with nothing. Other places still
succeed; failures are reported at the end.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.civicplus import fetch_agenda_center  # noqa: E402
from lib.corecode import fetch_council_meetings, DEFAULT_MEETINGS_PATH  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
OUT_DIR = os.path.join(ROOT, 'assets', 'data')


def load_registry(path):
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('places', []) if data else []


def _norm(name):
    return ' '.join((name or '').lower().split())


def fetch_meetings(cfg):
    """Dispatch on platform. Returns (meetings, bodies_seen) or (None, None)."""
    platform = cfg.get('platform')
    base = cfg['base_url'].rstrip('/')
    if platform == 'civicplus':
        return fetch_agenda_center(base, module_id=cfg.get('agenda_module_id', 65))
    if platform == 'corecode':
        return fetch_council_meetings(
            base, path=cfg.get('meetings_path', DEFAULT_MEETINGS_PATH))
    raise ValueError('unknown meetings platform %r' % platform)


def source_url(cfg):
    base = cfg['base_url'].rstrip('/')
    platform = cfg.get('platform')
    if platform == 'civicplus':
        return '%s/AgendaCenter' % base
    if platform == 'corecode':
        return base + cfg.get('meetings_path', DEFAULT_MEETINGS_PATH)
    return base


def build_place(place):
    """Fetch + normalize one place's meetings. Returns the output dict, or None."""
    slug = place['slug']
    cfg = (place.get('domains') or {}).get('meetings')
    if not cfg:
        return 'skip'  # place has no meetings domain — not an error

    print('Fetching meetings for %s (%s)...' % (place['name'], cfg.get('platform')))
    meetings, bodies_seen = fetch_meetings(cfg)

    if meetings is None:
        print('  ERROR: could not fetch meetings source for %s' % slug)
        return None
    if not meetings:
        print('  ERROR: parsed zero meetings for %s (source markup may have changed)'
              % slug)
        return None

    with_minutes = sum(1 for m in meetings if m['minutesUrl'])
    print('  %d meeting(s) across %d body(ies); %d with minutes'
          % (len(meetings), len(bodies_seen), with_minutes))

    expected = {_norm(b) for b in (cfg.get('bodies') or {})}
    present = {_norm(b) for b in bodies_seen}
    for missing in sorted(expected - present):
        print('  note: registry body not present on source: %s' % missing)

    return {
        'metadata': {
            'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': '%s (%s)' % (place['name'], cfg.get('platform')),
            'sourceUrl': source_url(cfg),
            'place': place['name'],
            'type': place.get('type'),
            'fips': place.get('fips'),
            'count': len(meetings),
        },
        'bodies': bodies_seen,
        'meetings': meetings,
    }


def write_place(slug, payload):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'local-%s-meetings.json' % slug)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    print('  Wrote %s' % out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='only build this place (default: all in registry)')
    ap.add_argument('--registry', default=DEFAULT_REGISTRY)
    args = ap.parse_args()

    places = load_registry(args.registry)
    if args.slug:
        places = [p for p in places if p['slug'] == args.slug]
        if not places:
            sys.exit('No place with slug %r in %s' % (args.slug, args.registry))

    failed = []
    built = 0
    for place in places:
        payload = build_place(place)
        if payload == 'skip':
            continue
        if payload is None:
            failed.append(place['slug'])
            continue
        write_place(place['slug'], payload)
        built += 1

    if failed:
        sys.exit('FAILED: %s' % ', '.join(failed))
    print('Done (%d place(s) with meetings).' % built)


if __name__ == '__main__':
    main()
