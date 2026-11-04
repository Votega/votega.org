#!/usr/bin/env python3
"""The recorded-votes index: derived from files, and consistent with the committed ones.

Run: python scripts/test_votes_index.py      (no network)

Note: no module-level `import yaml` (the CI test job installs no pip packages).
"""
import glob
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from lib.votes_index import build_index, votes_path

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


def place(slug, platform):
    return {'slug': slug, 'domains': {'meetings': {'platform': platform}}}


# --- built from files on disk -------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    meetings = [
        {'id': 1, 'date': '2026-03-02T18:00:00Z', 'items': [{'name': 'x'}]},
        {'id': 2, 'date': '2025-11-05T18:00:00Z', 'items': []},
    ]
    with open(votes_path(d, 'fulton'), 'w', encoding='utf-8') as f:
        json.dump({'meetings': meetings}, f)
    idx = build_index([
        place('fulton', 'legistar'),      # reader + file
        place('henry', 'civicclerk'),     # reader, no file
        place('clayton', 'civicplus'),    # no reader
        {'slug': 'bare'},                 # no domains at all
    ], d)['places']
    check('available entry', idx['fulton'], {
        'platform': 'legistar', 'status': 'available', 'meetings': 2,
        'meetingsWithVotes': 1, 'firstMeeting': '2025-11-05', 'lastMeeting': '2026-03-02'})
    check('reader without a file is not-published', idx['henry'],
          {'platform': 'civicclerk', 'status': 'not-published'})
    check('a platform with no reader is absent, not "none published"',
          ('clayton' in idx, 'bare' in idx), (False, False))

# --- the committed index agrees with the committed files ---------------------
index_path = os.path.join(ROOT, '_data', 'local_votes.json')
if os.path.exists(index_path):
    with open(index_path, encoding='utf-8') as f:
        committed = json.load(f)['places']
    on_disk = sorted(os.path.basename(p)[len('local-'):-len('-votes.json')]
                     for p in glob.glob(os.path.join(ROOT, 'assets', 'data', 'local-*-votes.json')))
    listed = sorted(s for s, v in committed.items() if v['status'] == 'available')
    check('every votes file is "available" in the index, and vice versa', listed, on_disk)

if failures:
    print('FAIL')
    for f in failures:
        print('  ' + f)
    sys.exit(1)
print('All checks passed.')
