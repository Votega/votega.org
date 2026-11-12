#!/usr/bin/env python3
"""Invariants of generate_school_meetings.py (phase 3e). No network, no pip packages.

Drives run() with an injected fetcher over the REAL Newton listing captured
2026-11-02 and the Incapsula block page (scripts/fixtures/).

What is pinned, and why:
  * The payload has the SAME shape as local-<slug>-meetings.json (metadata,
    bodies, meetings), so one renderer serves both.
  * It is keyed by GOSA district id, not place: a board is a district.
  * A BLOCKED listing writes nothing and is reported as failed - never recorded
    as a board with no meetings.
  * A listing that parses to ZERO meetings writes nothing (markup may have
    changed), the same refusal the place generator makes.
  * One district failing does not stop the others.
  * Only districts with a supported `meetings` block are fetched.

Run: python scripts/test_generate_school_meetings.py
"""

import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_school_meetings as G  # noqa: E402

LISTING = open(os.path.join(HERE, 'fixtures', 'simbli-newton-listing.html'),
               encoding='utf-8').read()
BLOCK = open(os.path.join(HERE, 'fixtures', 'simbli-incapsula-block.html'),
             encoding='utf-8').read()
EMPTY_GRID = LISTING[:LISTING.find('<tr')] if '<tr' in LISTING else LISTING

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


NEWTON = {'id': '707', 'name': 'Newton County', 'type': 'county',
          'meetings': {'platform': 'simbli', 'id': '4122'}}
OTHER = {'id': '776', 'name': 'Gainesville City', 'type': 'city',
         'meetings': {'platform': 'simbli', 'id': '4072'}}
NONE = {'id': '600', 'name': 'No Source County', 'type': 'county'}
DATA = {'countyDistricts': [NEWTON, NONE], 'cityDistricts': [OTHER]}

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


def serving(html):
    """Serve `html` for any district, rewriting the captured S=4122 to the key
    asked for. The parser rejects rows carrying another district's key, so a
    fixture has to carry the right one - which is itself a guard worth keeping."""
    def fetch(url, label=None, timeout=30):
        key = url.split('S=')[-1]
        return html.replace('4122', key).encode('utf-8')
    return fetch


class Sink:
    def __init__(self):
        self.files = {}

    def __call__(self, path, payload, **kw):
        self.files[os.path.basename(path)] = payload


print('Selecting districts')
check([d['id'] for d, _ in G.configured_districts(DATA)] == ['707', '776'],
      'only districts with a simbli meetings block are selected')
check(G.out_path('707').endswith('school-707-meetings.json'),
      'output is keyed by district id')

print('\nA served listing')
p = G.build_payload(NEWTON, NEWTON['meetings'], fetch=serving(LISTING), now=NOW)
check(p is not None and p['metadata']['count'] == 7, 'builds a payload with 7 meetings')
check(p['metadata']['districtId'] == '707' and p['metadata']['district'] == 'Newton County',
      'metadata names the district and its GOSA id')
check(p['metadata']['generatedAt'] == '2026-11-12T09:00:00Z', 'generatedAt is the run time')
check(p['metadata']['sourceUrl'].endswith('SB_MeetingListing.aspx?S=4122'),
      'sourceUrl is the board listing')
check(p['bodies'] == ['Board of Education'], 'body is the governing body')
check(set(p['meetings'][0]) >= {'body', 'date', 'id', 'title', 'agendaUrl', 'minutesUrl',
                                 'videoUrl', 'hasPreviousVersions'},
      'meeting rows carry the place-meetings fields')

print('\nFailure policy')
sink = Sink()
w, f = G.run(DATA, write=sink, fetch=serving(LISTING), now=NOW, attempts=1)
check(w == ['707', '776'] and not f, 'both configured districts are written')
check(sorted(sink.files) == ['school-707-meetings.json', 'school-776-meetings.json'],
      'one file per district')

sink = Sink()
w, f = G.run(DATA, write=sink, fetch=serving(BLOCK), attempts=2, pause=0,
             sleep=lambda s: None)
check(not w and f == ['707', '776'] and not sink.files,
      'a blocked listing writes nothing and is reported failed')

sink = Sink()
w, f = G.run(DATA, write=sink, fetch=serving(EMPTY_GRID), attempts=1)
check(not w and f == ['707', '776'] and not sink.files,
      'a listing with no meetings writes nothing')

calls = {}


def mixed(url, label=None, timeout=30):
    calls[url] = calls.get(url, 0) + 1
    return (LISTING if 'S=4122' in url else BLOCK).encode('utf-8')


sink = Sink()
w, f = G.run(DATA, write=sink, fetch=mixed, attempts=1)
check(w == ['707'] and f == ['776'] and list(sink.files) == ['school-707-meetings.json'],
      'one district failing does not stop the others')

sink = Sink()
w, f = G.run(DATA, only='776', write=sink, fetch=serving(LISTING), attempts=1)
check(w == ['776'] and not f, '--district limits the run')

sink = Sink()
w, f = G.run(DATA, dry_run=True, write=sink, fetch=serving(LISTING), attempts=1)
check(w == ['707', '776'] and not sink.files, '--dry-run writes nothing')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll school-meetings generator invariants hold.')
