#!/usr/bin/env python3
"""Link our school-board meetings to their Georgia Commons summary pages.

Georgia Commons (georgiacommons.org, a project of Georgia Civic Data) reads the
MINUTES a board posts and publishes an AI-written summary of each meeting. We read
the AGENDA, which is posted before the meeting. Linking the two lets a meeting row
show "what's coming" from us and, once the minutes exist, "what happened" from
them. Timing differs a lot by board: Baldwin posts minutes within about a week,
Newton about three months later (measured 2026-11-19).

Writes assets/data/georgia-commons-meetings.json:

    { metadata: { generatedAt, source, apiUrl, count, districts, carriedForward[] },
      districts: { <GOSA district id>: { <Simbli MID>: { url, date } } } }

THE JOIN IS EXACT, NEVER A DATE GUESS. Each Georgia Commons meeting lists its
sources, and a Simbli minutes source carries the board's own URL
(ViewMeeting.aspx?S=<site>&MID=<meeting>&T=1). Our meeting `id` is that MID and our
agendaUrl carries the same S. A row is linked only when both match; a board can hold
two meetings on one date (a work session and a regular session), so a date match
would link the wrong one.

ONLY THE LINK IS STORED. Their summaries' license is not settled
(docs/georgia-civic-data-collaboration.md: link out, label as AI-written, do not copy
text). So `headline` is deliberately not kept; the page prints our own label.

Failure policy (never overwrite good data with worse):
  * A district whose API read fails keeps its previous links (listed under
    metadata.carriedForward) and the run exits 1 after writing the rest.
  * A district that answers with zero meetings is fine (their coverage may not
    have reached it) but never removes links we had: a summary page, once
    published, is not expected to disappear, and their feed reports withdrawals
    separately. Previous links not seen this run are kept.

Usage:
    python scripts/generate_georgia_commons_links.py [--district 707] [--dry-run]
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.http import fetch_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'assets', 'data')
OUT_PATH = os.path.join(DATA_DIR, 'georgia-commons-meetings.json')
API = 'https://api.georgiacommons.org/api/meetings'
PAGE = 100
MAX_PAGES = 50  # 5,000 meetings per board: far above any board, stops a runaway loop
SITE_HOST = 'https://georgiacommons.org/'

_SCHOOL_FILE = re.compile(r'school-(\d+)-meetings\.json$')


def simbli_key(url):
    """(S, MID) from a Simbli ViewMeeting URL, or None. Case-insensitive keys."""
    if not isinstance(url, str) or 'simbli' not in url.lower():
        return None
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    q = {k.lower(): v for k, v in q.items()}
    s, mid = (q.get('s') or [None])[0], (q.get('mid') or [None])[0]
    if not s or not mid or not s.isdigit() or not mid.isdigit():
        return None
    return s, mid


def our_districts(data_dir=DATA_DIR, only=None):
    """{district id: {(S, MID) for every meeting we hold}} from school-*-meetings.json."""
    out = {}
    for path in sorted(glob.glob(os.path.join(data_dir, 'school-*-meetings.json'))):
        m = _SCHOOL_FILE.search(path.replace('\\', '/'))
        if not m or (only and m.group(1) != only):
            continue
        with open(path, encoding='utf-8') as f:
            meetings = (json.load(f) or {}).get('meetings') or []
        keys = set()
        for row in meetings:
            k = simbli_key(row.get('agendaUrl')) or simbli_key(row.get('minutesUrl'))
            if k and str(row.get('id')) == k[1]:
                keys.add(k)
        out[m.group(1)] = keys
    return out


def fetch_district(district, fetch=fetch_json):
    """Every Georgia Commons meeting for one district with minutes, or None on failure."""
    rows, offset = [], 0
    for _ in range(MAX_PAGES):
        url = '%s?%s' % (API, urllib.parse.urlencode(
            {'district_code': district, 'has': 'minutes', 'limit': PAGE, 'offset': offset}))
        data = fetch(url, label='Georgia Commons meetings %s @%s' % (district, offset))
        if not isinstance(data, dict) or not isinstance(data.get('meetings'), list):
            return None
        rows.extend(data['meetings'])
        nxt = data.get('next_offset')
        if nxt is None or not data['meetings'] or nxt <= offset:
            return rows
        offset = nxt
    print('  ERROR: district %s paged past %s meetings; refusing a partial read'
          % (district, PAGE * MAX_PAGES))
    return None


def match(district, gc_meetings, ours):
    """{MID: {url, date}} for Georgia Commons meetings that are exactly ours."""
    links = {}
    for gm in gc_meetings or []:
        juris = gm.get('jurisdiction') or {}
        if str(juris.get('district_code') or '') != district:
            continue
        url = gm.get('url')
        if not isinstance(url, str) or not url.startswith(SITE_HOST):
            continue
        for src in gm.get('sources') or []:
            if src.get('kind') != 'minutes':
                continue
            k = simbli_key(src.get('url'))
            if k and k in ours:
                links[k[1]] = {'url': url, 'date': gm.get('date') or None}
    return links


def load_previous(path=OUT_PATH):
    try:
        with open(path, encoding='utf-8') as f:
            return (json.load(f) or {}).get('districts') or {}
    except (OSError, ValueError):
        return {}


def run(data_dir=DATA_DIR, out_path=OUT_PATH, only=None, fetch=fetch_json,
        now=None, dry_run=False):
    """Build and write the sidecar. Returns the list of districts that failed."""
    ours = our_districts(data_dir, only)
    previous = load_previous(out_path)
    districts = {k: dict(v) for k, v in previous.items()}
    failed, carried = [], []

    for district, keys in sorted(ours.items()):
        gc = fetch_district(district, fetch=fetch)
        if gc is None:
            print('  ERROR: Georgia Commons read failed for district %s; keeping previous links'
                  % district)
            failed.append(district)
            if district in previous:
                carried.append(district)
            continue
        fresh = match(district, gc, keys)
        merged = dict(previous.get(district) or {})
        merged.update(fresh)
        # Drop only links whose meeting WE no longer hold: there is no row to hang it on.
        held = {mid for _, mid in keys}
        merged = {mid: v for mid, v in merged.items() if mid in held}
        districts[district] = dict(sorted(merged.items(), key=lambda kv: int(kv[0])))
        print('  district %s: %s Georgia Commons meetings, %s linked to ours'
              % (district, len(gc), len(districts[district])))

    # A district whose school file is gone has nothing to link to.
    if not only:
        districts = {d: v for d, v in districts.items() if d in ours}

    now = now or datetime.now(timezone.utc)
    payload = {
        'metadata': {
            'generatedAt': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': 'Georgia Commons (georgiacommons.org), a project of Georgia Civic Data',
            'apiUrl': API,
            'summaryLabel': 'AI-written summary from Georgia Commons',
            'count': sum(len(v) for v in districts.values()),
            'districts': len(districts),
            'carriedForward': carried or None,
        },
        'districts': dict(sorted(districts.items())),
    }
    if dry_run:
        print(json.dumps(payload['metadata'], indent=2))
    else:
        write_json_atomic(out_path, payload, indent=2)
        print('Wrote %s (%s links)' % (os.path.relpath(out_path, ROOT), payload['metadata']['count']))
    return failed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--district', help='Only this GOSA district id')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    failed = run(only=args.district, dry_run=args.dry_run)
    if failed:
        print('FAILED districts: %s' % ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
