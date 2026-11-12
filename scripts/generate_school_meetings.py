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


def run(data, only=None, dry_run=False, write=write_json_atomic, **kw):
    """Process the registry. Returns (written, failed) lists of district ids."""
    written, failed = [], []
    for district, cfg in configured_districts(data):
        if only and district['id'] != only:
            continue
        print('Fetching meetings for %s (simbli %s)...' % (district['name'], cfg['id']))
        try:
            payload = build_payload(district, cfg, **kw)
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
    args = ap.parse_args()
    with open(REGISTRY, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    written, failed = run(data, only=args.district, dry_run=args.dry_run)
    print('\nDone: %d written, %d failed.' % (len(written), len(failed)))
    if failed:
        print('Failed districts (committed files left untouched): %s' % ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
