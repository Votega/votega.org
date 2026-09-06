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
from lib.civicclerk import fetch_civicclerk_meetings, portal_url  # noqa: E402

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
    if platform == 'civicplus':
        return fetch_agenda_center(cfg['base_url'].rstrip('/'),
                                   module_id=cfg.get('agenda_module_id', 65))
    if platform == 'corecode':
        return fetch_council_meetings(
            cfg['base_url'].rstrip('/'),
            path=cfg.get('meetings_path', DEFAULT_MEETINGS_PATH))
    if platform == 'civicclerk':
        return fetch_civicclerk_meetings(cfg['subdomain'])
    raise ValueError('unknown meetings platform %r' % platform)


def source_url(cfg):
    platform = cfg.get('platform')
    if platform == 'civicplus':
        return '%s/AgendaCenter' % cfg['base_url'].rstrip('/')
    if platform == 'corecode':
        return cfg['base_url'].rstrip('/') + cfg.get('meetings_path', DEFAULT_MEETINGS_PATH)
    if platform == 'civicclerk':
        return portal_url(cfg['subdomain'])
    return cfg.get('base_url')


def scope_bodies(cfg, meetings, slug):
    """Narrow meetings to the bodies we publish, and optionally relabel them.

    Policy (see LOCAL-GOVERNMENT-IA.md): as counties are onboarded we surface only
    the top-level legislative body (the Board of Commissioners), not every board,
    commission, and authority. Three optional keys under domains.meetings:

      include_bodies  keep only meetings whose body contains one of these
                      (case-insensitive substring) — an allow-list.
      exclude_bodies  drop meetings whose body contains one of these.
      body_label      relabel every kept meeting to this single body name, for
                      sources (e.g. Cobb's CivicClerk) that store the meeting
                      *type* in the body field rather than a clean body name.

    Returns (meetings, bodies_seen) recomputed from the kept set.
    """
    inc = [p.lower() for p in (cfg.get('include_bodies') or [])]
    exc = [p.lower() for p in (cfg.get('exclude_bodies') or [])]
    label = cfg.get('body_label')

    if inc or exc:
        def keep(m):
            b = (m.get('body') or '').lower()
            if inc and not any(p in b for p in inc):
                return False
            if exc and any(p in b for p in exc):
                return False
            return True
        meetings = [m for m in meetings if keep(m)]

    if label:
        for m in meetings:
            m['body'] = label

    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen


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

    meetings, bodies_seen = scope_bodies(cfg, meetings, slug)
    if not meetings:
        print('  ERROR: body filter for %s matched zero meetings — check '
              'include_bodies/exclude_bodies against the source' % slug)
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
