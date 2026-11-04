#!/usr/bin/env python3
"""Recorded motions and named votes for CivicClerk and Legistar places.

Writes assets/data/local-<slug>-votes.json for each registry place on the
`civicclerk` or `legistar` platform whose portal publishes votes (see
lib/civicclerk_votes.py for which CivicClerk portals do). A place with no votes anywhere gets no file, so a portal that
never records them is not advertised as having an empty record.

Incremental: a meeting already read and older than RECHECK_DAYS is carried
forward from the committed file, so a normal run re-reads only the recent
meetings. A quiet run rewrites nothing (the file keeps its generatedAt unless
the meetings changed).

    python scripts/generate_meeting_votes.py [--slug douglas] [--years 2]   (Legistar reads years*12 months, 12 by default)
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402

from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.civicclerk_votes import fetch_votes as fetch_civicclerk  # noqa: E402
from lib.legistar_votes import fetch_votes as fetch_legistar  # noqa: E402
from lib.votes_index import build_index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
DATA = os.path.join(ROOT, 'assets', 'data')
INDEX_PATH = os.path.join(ROOT, '_data', 'local_votes.json')


def out_path(slug):
    return os.path.join(DATA, 'local-%s-votes.json' % slug)


def load_previous(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f).get('meetings')


def build(slug, cfg, years):
    path = out_path(slug)
    previous = load_previous(path)
    if cfg['platform'] == 'civicclerk':
        meetings = fetch_civicclerk(cfg['subdomain'], previous=previous, years=years)
        source = 'CivicClerk meeting records (%s.api.civicclerk.com)' % cfg['subdomain']
    else:
        meetings = fetch_legistar(cfg['client'], previous=previous,
                                  months=years * 12 if years != 2 else 12)
        source = 'Legistar Web API (webapi.legistar.com/v1/%s)' % cfg['client']
    if meetings is None:
        print('  %s: could not read the portal; leaving the file as it is' % slug)
        return False
    with_votes = sum(1 for m in meetings if m['items'])
    if previous is None and not with_votes:
        print('  %s: %d meetings read, none with recorded votes; no file' % (slug, len(meetings)))
        return True
    if previous == meetings:
        print('  %s: unchanged (%d meetings, %d with votes)' % (slug, len(meetings), with_votes))
        return True
    payload = {
        'metadata': {
            'generatedAt': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': source,
            'platform': cfg['platform'],
            'count': len(meetings),
            'meetingsWithVotes': with_votes,
        },
        'meetings': meetings,
    }
    write_json_atomic(path, payload, separators=(',', ':'))
    print('  %s: wrote %d meetings, %d with votes' % (slug, len(meetings), with_votes))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug')
    ap.add_argument('--years', type=int, default=2)
    args = ap.parse_args()
    with open(REGISTRY, encoding='utf-8') as f:
        places = yaml.safe_load(f).get('places', [])
    failed = 0
    for p in places:
        cfg = (p.get('domains') or {}).get('meetings') or {}
        if cfg.get('platform') not in ('civicclerk', 'legistar') or (args.slug and p['slug'] != args.slug):
            continue
        if not build(p['slug'], cfg, args.years):
            failed += 1
    write_index(places)
    if failed:
        sys.exit(1)


def write_index(places):
    """Refresh _data/local_votes.json from the files on disk (see lib/votes_index).
    Runs even after a failed portal read: the index describes the files that
    exist, and a place left as-is keeps its entry. Rewritten only on a change."""
    index = build_index(places, DATA)
    previous = None
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, encoding='utf-8') as f:
            previous = json.load(f)
    if previous == index:
        return
    write_json_atomic(INDEX_PATH, index, indent=2)
    print('wrote %s (%d places)' % (os.path.relpath(INDEX_PATH, ROOT), len(index['places'])))


if __name__ == '__main__':
    main()
