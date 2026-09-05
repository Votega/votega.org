#!/usr/bin/env python3
"""Validate generated local-government meeting JSON before it is committed.

The source is scraped, so the real failure mode is silent: a place reskins its
site, the adapter matches nothing (or garbage), and a valid-but-empty/wrong file
gets committed. This guard makes that loud. It runs in update-local-government.yml
and can be run locally after the generator.

Checks per place file (assets/data/local-<slug>-meetings.json):
  - structural: metadata / bodies / meetings present, metadata.count == len(meetings)
  - non-empty, and count >= --min-meetings (default 1)
  - each meeting: body set, date is YYYY-MM-DD, has an agenda or minutes URL
  - link liveness: a small sample of file URLs return HTTP 200
  - coverage: warn (not fail) on a registry body absent from the file

Usage:
    python scripts/validate_place_meetings.py [--slug newton] [--min-meetings N]
                                              [--sample N] [--no-network]

Exits 1 on any hard failure.
"""

import argparse
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.http import fetch_bytes  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
DATA_DIR = os.path.join(ROOT, 'assets', 'data')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _norm(name):
    return ' '.join((name or '').lower().split())


def check_place(place, min_meetings, sample, network):
    slug = place['slug']
    cfg = (place.get('domains') or {}).get('meetings')
    if not cfg:
        return [], []  # no meetings domain — nothing to validate

    path = os.path.join(DATA_DIR, 'local-%s-meetings.json' % slug)
    errors, warnings = [], []

    if not os.path.exists(path):
        return ['%s: missing file %s' % (slug, path)], []

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    meta = data.get('metadata') or {}
    meetings = data.get('meetings')
    bodies = data.get('bodies')

    if not isinstance(meetings, list):
        return ['%s: "meetings" missing or not a list' % slug], []
    if not isinstance(bodies, list):
        errors.append('%s: "bodies" missing or not a list' % slug)

    if len(meetings) < min_meetings:
        errors.append('%s: %d meeting(s) < minimum %d'
                      % (slug, len(meetings), min_meetings))
    if meta.get('count') != len(meetings):
        errors.append('%s: metadata.count %r != %d meetings'
                      % (slug, meta.get('count'), len(meetings)))
    for field in ('generatedAt', 'source', 'sourceUrl', 'place'):
        if not meta.get(field):
            errors.append('%s: metadata.%s missing' % (slug, field))

    for i, m in enumerate(meetings):
        where = '%s meeting[%d]' % (slug, i)
        if not m.get('body'):
            errors.append('%s: body missing' % where)
        if not DATE_RE.match(m.get('date') or ''):
            errors.append('%s: bad date %r' % (where, m.get('date')))
        # A meeting is a usable record if it links ANY artifact. Most platforms
        # publish agendas/minutes; CoreCode (Covington) publishes minutes + video
        # only, and the newest meetings may have just the video until minutes post.
        if not (m.get('agendaUrl') or m.get('minutesUrl') or m.get('videoUrl')):
            errors.append('%s: no agenda, minutes, or video URL' % where)

    present = {_norm(b) for b in (bodies or [])}
    for b in (cfg.get('bodies') or {}):
        if _norm(b) not in present:
            warnings.append('%s: registry body absent from output: %s' % (slug, b))

    if network and meetings:
        urls = []
        for m in meetings:
            urls += [u for u in (m.get('agendaUrl'), m.get('minutesUrl')) if u]
            if len(urls) >= sample:
                break
        for url in urls[:sample]:
            if fetch_bytes(url, timeout=30, retries=2, verbose=False) is None:
                errors.append('%s: dead link %s' % (slug, url))
            else:
                print('  ok: %s' % url)

    print('%s: %d meetings, %d bodies%s'
          % (slug, len(meetings), len(bodies or []),
             '' if not warnings else ' (%d warning(s))' % len(warnings)))
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='only validate this place')
    ap.add_argument('--min-meetings', type=int, default=1)
    ap.add_argument('--sample', type=int, default=3,
                    help='file links to liveness-check per place')
    ap.add_argument('--no-network', action='store_true',
                    help='skip link-liveness checks (offline/CI-lite)')
    args = ap.parse_args()

    with open(REGISTRY, encoding='utf-8') as f:
        places = (yaml.safe_load(f) or {}).get('places', [])
    if args.slug:
        places = [p for p in places if p['slug'] == args.slug]
        if not places:
            sys.exit('No place with slug %r' % args.slug)

    all_errors, all_warnings = [], []
    for place in places:
        errors, warnings = check_place(
            place, args.min_meetings, args.sample, not args.no_network)
        all_errors += errors
        all_warnings += warnings

    for w in all_warnings:
        print('WARNING: %s' % w)
    if all_errors:
        print('\n%d error(s):' % len(all_errors))
        for e in all_errors:
            print('  - %s' % e)
        sys.exit(1)
    print('\nAll place meeting files valid.')


if __name__ == '__main__':
    main()
