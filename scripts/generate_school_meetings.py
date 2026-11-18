#!/usr/bin/env python3
"""Generate school-board meeting data from the district registry (phase 3e).

Reads _data/school_districts.yml and, for each district that declares a
`meetings` block, fetches that board's listing and writes

    assets/data/school-<districtId>-meetings.json

in the SAME schema the place meetings use (metadata, bodies[], meetings[]), so any
surface can render it with the code that already renders local-<slug>-meetings.json.
Only meeting LINKS are stored, never the documents.

Keyed by GOSA district id, not by place: a board is a district, and one place can
be served by several boards (docs/LOCAL-EXPANSION-SCOPE.md, §3.5.2).

Usage:
    python scripts/generate_school_meetings.py [--district 707] [--dry-run]
    python scripts/generate_school_meetings.py --from-file 707=listing.html [...]

Simbli sits behind Incapsula, which blocks every non-browser client (GitHub's
runners and a home connection alike). `--from-file DISTRICT=PATH` parses a listing
page saved from a real browser instead of fetching, the same pattern as
generate_place_meetings.py --from-file. Only that district is built; the rest of
the registry is left alone. A saved page is a snapshot, so the file it writes is
exactly as fresh as the page you saved.

Failure policy (never overwrite good data with worse):
  * A blocked listing (Incapsula) or a failed fetch leaves the committed file
    untouched and is reported; the other districts still run.
  * A listing that parses to ZERO meetings is treated as a failure, not as "this
    board has no meetings" — the markup may have changed.
  * Exit 1 if any district failed, after all have been tried, so the failure
    notifier opens an issue while healthy districts still commit.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.simbli import (  # noqa: E402
    DEFAULT_BODY, SimbliBlocked, fetch_simbli_meetings, listing_url,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'school_districts.yml')
OUT_DIR = os.path.join(ROOT, 'assets', 'data')


def out_path(district_id):
    return os.path.join(OUT_DIR, 'school-%s-meetings.json' % district_id)


def configured_districts(data):
    """[(district dict, meetings cfg)] for every district with a supported source."""
    found = []
    for kind in ('countyDistricts', 'cityDistricts'):
        for d in (data or {}).get(kind) or []:
            cfg = d.get('meetings')
            if isinstance(cfg, dict) and cfg.get('platform') == 'simbli' and cfg.get('id'):
                found.append((d, cfg))
    return found


def build_payload(district, cfg, fetch=None, now=None, **fetch_kw):
    """Fetch one district and return its payload, or None on any failure.

    Raises SimbliBlocked untouched so the caller can report it as a block rather
    than as an empty board.
    """
    kwargs = dict(fetch_kw)
    if fetch is not None:
        kwargs['fetch'] = fetch
    body = cfg.get('body') or DEFAULT_BODY
    meetings, bodies = fetch_simbli_meetings(cfg['id'], body=body, **kwargs)
    if meetings is None:
        print('  ERROR: could not fetch the listing for %s' % district['name'])
        return None
    if not meetings:
        print('  ERROR: parsed zero meetings for %s (markup may have changed)'
              % district['name'])
        return None
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        'metadata': {
            'generatedAt': stamp,
            'source': '%s (simbli)' % district['name'],
            'sourceUrl': listing_url(cfg['id']),
            'district': district['name'],
            'districtId': district['id'],
            'type': district.get('type'),
            'count': len(meetings),
        },
        'bodies': bodies,
        'meetings': meetings,
    }


def saved_fetcher(path):
    """A fetch() that serves one saved listing page, for --from-file."""
    def fetch(url, label=None, timeout=30):
        with open(path, 'rb') as f:
            return f.read()
    return fetch


def run(data, only=None, dry_run=False, write=write_json_atomic, from_files=None, **kw):
    """Process the registry. Returns (written, failed) lists of district ids.

    `from_files` maps district id -> saved listing path. When given, ONLY those
    districts run, each parsed from its file with no network."""
    written, failed = [], []
    from_files = from_files or {}
    for district, cfg in configured_districts(data):
        if only and district['id'] != only:
            continue
        if from_files and district['id'] not in from_files:
            continue
        print('%s meetings for %s (simbli %s)...'
              % ('Parsing' if from_files else 'Fetching', district['name'], cfg['id']))
        try:
            call = dict(kw)
            if district['id'] in from_files:
                call['fetch'] = saved_fetcher(from_files[district['id']])
                call['attempts'] = 1
            payload = build_payload(district, cfg, **call)
        except SimbliBlocked as e:
            print('  BLOCKED: %s' % e)
            payload = None
        if payload is None:
            failed.append(district['id'])
            continue
        print('  %d meeting(s)' % payload['metadata']['count'])
        if not dry_run:
            os.makedirs(OUT_DIR, exist_ok=True)
            write(out_path(district['id']), payload, separators=(',', ':'))
        written.append(district['id'])
    return written, failed


def main():
    import yaml  # lazy: the tests inject parsed data and need no pip packages
    ap = argparse.ArgumentParser()
    ap.add_argument('--district', help='only this GOSA district id')
    ap.add_argument('--dry-run', action='store_true', help='fetch and parse, write nothing')
    ap.add_argument('--from-file', action='append', default=[], metavar='ID=PATH',
                    help='parse a listing saved from a browser instead of fetching '
                         '(repeatable; only those districts run)')
    args = ap.parse_args()
    from_files = {}
    for spec in args.from_file:
        did, _, path = spec.partition('=')
        if not did or not path or not os.path.isfile(path):
            sys.exit('--from-file needs DISTRICT_ID=PATH to an existing file, got %r' % spec)
        from_files[did] = path
    with open(REGISTRY, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    unknown = [d for d in from_files if d not in {x['id'] for x, _ in configured_districts(data)}]
    if unknown:
        sys.exit('--from-file names district(s) with no meetings source: %s' % ', '.join(unknown))
    written, failed = run(data, only=args.district, dry_run=args.dry_run,
                          from_files=from_files)
    print('\nDone: %d written, %d failed.' % (len(written), len(failed)))
    if failed:
        print('Failed districts (committed files left untouched): %s' % ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
