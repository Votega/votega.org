#!/usr/bin/env python3
"""
List the Georgia legislative sessions Open States knows about, with the exact
`identifier` string each generator needs.

Run this at a biennium changeover instead of guessing the session string. The
identifier is not always the obvious pattern, and guessing wrong produces failures
that look identical to an expired key or an outage — see the notes in
RECURRING-TASKS.md under "When a new GA legislative session starts".

Costs one API request. Open States enforces 250 requests/day shared across every
job using the key, so this is safe to run even on a busy day.

Requires OPENSTATES_API_KEY.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

API_KEY  = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"

# Constants the generators use today, so drift is visible at a glance.
CURRENT_SESSIONS = {
    'scripts/generate_ga_bills_data.py': '2025_26',
    'scripts/generate_ga_votes_data.py': '2025_26',
}


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    url = f"{BASE_URL}/jurisdictions/{urllib.parse.quote(GA_JURISDICTION, safe='')}"
    req = urllib.request.Request(url, headers={
        'X-API-Key': API_KEY,
        'Accept': 'application/json',
        'User-Agent': 'votega.org/1.0',
    })

    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"HTTP {e.code}: {body[:300]}", file=sys.stderr)
        if e.code == 429:
            print("\nThe 250/day quota is shared across every job using this key. "
                  "It resets daily — retry tomorrow, or after the scheduled jobs "
                  "have finished for the day.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    sessions = data.get('legislative_sessions') or []
    if not sessions:
        print("No legislative sessions returned.", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    in_use = set(CURRENT_SESSIONS.values())

    print(f"Georgia legislative sessions known to Open States ({len(sessions)}):\n")
    print(f"  {'identifier':<14} {'start':<12} {'end':<12} name")
    print(f"  {'-'*14} {'-'*12} {'-'*12} {'-'*40}")
    for s in sorted(sessions, key=lambda x: x.get('start_date') or ''):
        ident = s.get('identifier') or '?'
        start = s.get('start_date') or ''
        end   = s.get('end_date') or ''
        marks = []
        if ident in in_use:
            marks.append('<- in use')
        if start and start > today:
            marks.append('upcoming')
        elif end and end < today:
            marks.append('ended')
        print(f"  {ident:<14} {start:<12} {end:<12} {s.get('name','')} "
              f"{' '.join(marks)}")

    print("\nGenerators currently pinned to:")
    for path, sess in CURRENT_SESSIONS.items():
        known = any(s.get('identifier') == sess for s in sessions)
        print(f"  {path:<42} {sess} {'' if known else '  <-- NOT a known identifier!'}")

    upcoming = [s for s in sessions
                if (s.get('start_date') or '') > today and s.get('identifier') not in in_use]
    if upcoming:
        nxt = sorted(upcoming, key=lambda x: x['start_date'])[0]
        print(f"\nNext session not yet in use: {nxt['identifier']} "
              f"(starts {nxt.get('start_date')})")
        print("  Bump GA_SESSION / SESSION_NAME in both generators once bills start "
              "appearing under it — early, while the full pull it triggers is still small.")


if __name__ == '__main__':
    main()
