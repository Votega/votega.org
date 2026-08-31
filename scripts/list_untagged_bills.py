#!/usr/bin/env python3
"""
List GA bills (HB/SB) that have no subject tag, reading the committed
assets/data/ga-bills.json directly. No API key, no Open States quota — this
reads the same `subjects` field generate_ga_bills_data.py already wrote, so it
reflects the current committed data.

Use it to find bills that need a manual subject added to
assets/data/ga-bills-subjects.json (keyed by identifier, e.g. "HB 739": ["HEALTH"]).
Subject values must match the canonical Open States taxonomy used elsewhere in
ga-bills.json, except "Local / Municipal" (this site's own tag for county/city
bills with no upstream subject). After editing the overrides file, re-run
generate_ga_bills_data.py to apply.

Note: generate_ga_bills_data.py also writes scripts/ga-bills-review.csv on every
run — but that requires a live fetch. This script is the offline equivalent for a
quick check or to correct an existing tag.

Usage:
    python scripts/list_untagged_bills.py                 # list untagged HB/SB bills
    python scripts/list_untagged_bills.py --show "SB 30"  # show one bill's current subjects (to correct it)
    python scripts/list_untagged_bills.py path/to/ga-bills.json   # non-default data file
"""

import json
import os
import sys

DEFAULT_FILE = os.path.join('assets', 'data', 'ga-bills.json')


def chamber_label(chamber):
    return {'lower': 'House', 'upper': 'Senate'}.get(chamber, chamber or '?')


def load_bills(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)['bills']


def show_bill(bills, identifier):
    matches = [b for b in bills if b['identifier'].upper() == identifier.upper()]
    if not matches:
        print(f'No bill found with identifier "{identifier}".')
        return 1
    for b in matches:
        subs = b.get('subjects') or []
        print(f"{b['identifier']} [{chamber_label(b['chamber'])}]  ({b['session']})")
        print(f"  title:    {b['title']}")
        print(f"  status:   {b.get('status', '')}")
        print(f"  subjects: {subs if subs else '(none)'}")
    return 0


def list_untagged(bills):
    actual = [b for b in bills if b['billType'] == 'bill']
    untagged = [b for b in actual if not b.get('subjects')]
    print(f'Actual bills (HB/SB): {len(actual)}')
    print(f'Untagged:             {len(untagged)}')
    if not untagged:
        print('\nNothing to tag. All HB/SB bills currently carry a subject.')
        return 0
    print()
    for b in sorted(untagged, key=lambda x: x['identifier']):
        print(f"{b['identifier']:9} [{chamber_label(b['chamber']):6}] "
              f"{(b.get('status') or '')[:30]:30} | {b['title'][:75]}")
    print(f"\nAdd tags to assets/data/ga-bills-subjects.json, then re-run "
          f"generate_ga_bills_data.py.")
    return 0


def main(argv):
    args = argv[1:]
    show_id = None
    if args and args[0] == '--show':
        if len(args) < 2:
            sys.exit('Usage: python scripts/list_untagged_bills.py --show "<identifier>"')
        show_id = args[1]
        args = args[2:]
    path = args[0] if args else DEFAULT_FILE
    if not os.path.exists(path):
        sys.exit(f'Data file not found: {path}\n'
                 f'Run generate_ga_bills_data.py first, or pass the path explicitly.')
    bills = load_bills(path)
    if show_id:
        return show_bill(bills, show_id)
    return list_untagged(bills)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
