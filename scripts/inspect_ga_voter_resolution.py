#!/usr/bin/env python3
"""Diagnose why roll-call rows fail to resolve to a GA legislator.

The 1.5 fix (lib/ga_voters.resolve_voter) moved the name fallback so it fires on
an *unresolvable* OCD person id rather than only a missing one. The first run
after that change still left coverage at 194/232, with 40 ghost ids and 259 rows
carrying no usable id or name — the fallback recovered only 3 rows. Something
about `voter_name` is not what the matcher assumes.

This fetches the same curated bills the generator does and reports, per roll
call: the inferred chamber, how each row resolved, and — the point of the
exercise — the actual `voter_name` values for rows that failed, next to what the
matcher made of them.

Read-only. Costs one Open States request per curated bill (9 today).

Usage:
  python scripts/inspect_ga_voter_resolution.py            # all curated bills
  python scripts/inspect_ga_voter_resolution.py "SB 233"   # just one
"""

import json
import os
import sys
import urllib.parse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ga_voters import (MemberIndex, event_chamber, new_stats,  # noqa: E402
                           normalize_voter_name, resolve_voter)
from lib.http import fetch_json  # noqa: E402

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
CURATED_BILLS_FILE = "assets/data/curated-ga-bills.json"
MEMBERS_FILE = "assets/data/ga-members.json"

SAMPLE = 12


def fetch_bill(session, identifier):
    params = urllib.parse.urlencode([
        ('jurisdiction', GA_JURISDICTION),
        ('session', session),
        ('identifier', identifier),
        ('include', 'votes'),
    ])
    data = fetch_json(f"{BASE_URL}/bills?{params}",
                      headers={'X-API-Key': API_KEY or '', 'Accept': 'application/json'},
                      redact=API_KEY)
    results = (data or {}).get('results') or []
    return results[0] if results else None


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY not set")
        return 1

    index = MemberIndex(MEMBERS_FILE)
    print(f"Loaded {len(index)} members from {MEMBERS_FILE}")
    print(f"Name index entries: {len(index.by_name)} "
          f"({sum(1 for v in index.by_name.values() if v is None)} ambiguous)\n")

    with open(CURATED_BILLS_FILE, encoding='utf-8') as fh:
        curated = json.load(fh).get('ga', [])
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    if wanted:
        curated = [c for c in curated if c['identifier'] == wanted]

    totals = new_stats()
    ghost_ids = Counter()
    ghost_names, unresolved_names, no_name_rows = [], [], 0
    field_presence = Counter()

    for entry in curated:
        bill = fetch_bill(entry['session'], entry['identifier'])
        if not bill:
            print(f"!! {entry['identifier']}: not found")
            continue

        for ve in bill.get('votes', []):
            if ve.get('motion_classification') != ['passage']:
                continue
            chamber = event_chamber(ve.get('motion_text'), ve.get('organization'))
            rows = ve.get('votes', [])
            stats = new_stats()

            for pv in rows:
                voter = pv.get('voter') or {}
                # Which name field actually carries anything?
                for f, val in (('pv.voter_name', pv.get('voter_name')),
                               ('voter.name', voter.get('name'))):
                    if val:
                        field_presence[f] += 1
                if not (pv.get('voter_name') or voter.get('name')):
                    field_presence['(no name at all)'] += 1

                name = pv.get('voter_name') or voter.get('name')
                mid, how = resolve_voter(voter.get('id'), name, chamber, index)
                stats[how] += 1
                totals[how] += 1

                if how == 'ghost':
                    ghost_ids[voter.get('id')] += 1
                    if len(ghost_names) < 60:
                        ghost_names.append((voter.get('id'), name, chamber))
                elif how == 'unresolved':
                    if not name:
                        no_name_rows += 1
                    elif len(unresolved_names) < 60:
                        unresolved_names.append((name, chamber))

            print(f"{bill['identifier']:<9} {str(chamber):<24} rows={len(rows):<4} "
                  f"id={stats['id']:<4} alias={stats['alias']:<3} name={stats['name']:<3} "
                  f"ghost={stats['ghost']:<3} unresolved={stats['unresolved']}")

    print(f"\n=== totals ===\n{json.dumps(totals, indent=2)}")
    print(f"\nname-field presence across all rows: {dict(field_presence)}")
    print(f"rows with no name in either field: {no_name_rows}")

    print(f"\n=== distinct ghost ids ({len(ghost_ids)}) ===")
    for gid, n in ghost_ids.most_common():
        print(f"  {gid}  x{n}")

    print(f"\n=== sample GHOST rows (id present, unmatched) ===")
    for gid, name, ch in ghost_names[:SAMPLE]:
        key = (ch, normalize_voter_name(name))
        print(f"  voter_name={name!r:32} chamber={str(ch):<24} "
              f"normalized={normalize_voter_name(name)!r:26} in_index={key in index.by_name}")

    print(f"\n=== sample UNRESOLVED rows (no id) ===")
    for name, ch in unresolved_names[:SAMPLE]:
        key = (ch, normalize_voter_name(name))
        hit = index.by_name.get(key, '<<missing>>')
        print(f"  voter_name={name!r:32} chamber={str(ch):<24} "
              f"normalized={normalize_voter_name(name)!r:26} lookup={hit!r}")

    # If names are bare surnames, say so plainly — that changes the fix entirely.
    all_failed = [n for n, _ in unresolved_names] + [n for _, n, _ in ghost_names if n]
    if all_failed:
        one_token = sum(1 for n in all_failed if n and len(n.split()) == 1)
        print(f"\nfailed rows whose voter_name is a single token (bare surname?): "
              f"{one_token}/{len(all_failed)}")
        surnames = Counter(n.split()[-1].lower() for n in all_failed if n)
        print("most common failed surnames:", surnames.most_common(8))
        members_by_surname = Counter(m['name'].split()[-1].lower()
                                     for m in index.by_id.values() if m.get('name'))
        for sn, _ in surnames.most_common(5):
            print(f"  '{sn}': {members_by_surname.get(sn, 0)} sitting member(s) share it")

    # A ghost id is a real Open States person record — just one ga-members.json
    # does not carry. Ask the API who it is. That turns each ghost into a
    # concrete alias candidate instead of an unknown, which is the only safe way
    # to recover votes when voter_name is too ambiguous to match on.
    if ghost_ids:
        print(f"\n=== looking up {len(ghost_ids)} ghost id(s) via /people ===")
        ids = list(ghost_ids)
        for i in range(0, len(ids), 10):          # the endpoint takes repeated id params
            batch = ids[i:i + 10]
            q = urllib.parse.urlencode([('id', g) for g in batch] + [('per_page', 50)])
            data = fetch_json(f"{BASE_URL}/people?{q}",
                              headers={'X-API-Key': API_KEY or '',
                                       'Accept': 'application/json'},
                              redact=API_KEY)
            for p in (data or {}).get('results', []):
                cr = p.get('current_role') or {}
                name = p.get('name')
                chamber = {'upper': 'Senate',
                           'lower': 'House of Representatives'}.get(cr.get('org_classification'))
                key = (chamber, normalize_voter_name(name))
                match = index.by_name.get(key)
                print(f"  {p.get('id')}")
                print(f"      name={name!r} party={p.get('party')!r} "
                      f"district={cr.get('district')!r} chamber={chamber!r}")
                print(f"      -> ga-members.json match: {match!r}"
                      f"{'  (AMBIGUOUS)' if key in index.by_name and match is None else ''}")
                # District is the reliable join when the name is not.
                by_district = [m for m in index.by_id.values()
                               if m.get('chamber') == chamber
                               and str(m.get('district')) == str(cr.get('district'))]
                if by_district:
                    print(f"      -> by (chamber, district): "
                          + ', '.join(f"{m['name']} [{m['id']}]" for m in by_district))
            missing = set(batch) - {p.get('id') for p in (data or {}).get('results', [])}
            for g in missing:
                print(f"  {g}\n      !! no person record returned")

    return 0


if __name__ == '__main__':
    sys.exit(main())
