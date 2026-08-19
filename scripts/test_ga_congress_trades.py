#!/usr/bin/env python3
"""Tests for the trades generator's counter derivation and bioguide join.

Guards CODEBASE-REVIEW-2026-08-18.md finding 3.3: `_mergeInto` extended the
merged member's trade list but left `purchases`, `sales`, `lateFilings` and
`estVolume` describing only one of the two filers, so Michael Collins' card
showed 42 trades beside a volume covering 23 of them.

Runs offline against the committed ga-congress-trades.json.

Usage:
  python scripts/test_ga_congress_trades.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_ga_congress_trades import (  # noqa: E402
    derive_counters, filer_district, filer_surname, resolve_bioguide,
)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '..', 'assets', 'data', 'ga-congress-trades.json')

PASS, FAIL = [], []


def check(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"          got={got!r}  want={want!r}")


print('=== filer_surname / filer_district ===')
check('surname ignores a Jr suffix', filer_surname('Michael A. Collins Jr'), 'collins')
check('surname ignores a III suffix', filer_surname('Earl Leroy Carter III'), 'carter')
check('plain surname', filer_surname('Austin Scott'), 'scott')
check('empty name', filer_surname(''), '')
check('district from office string', filer_district('U.S. Representative — GA-12'), 12)
check('district with no hyphen', filer_district('U.S. Representative GA 07'), 7)
check('senator has no district', filer_district('U.S. Senator — GA'), None)
check('missing office', filer_district(None), None)

print('\n=== resolve_bioguide ===')
# One Collins; two Scotts — the collision the FEC generator already fixed.
BY_SURNAME = {
    'collins':   [(10, 'C001129')],
    'scott':     [(8, 'S001189'), (13, 'S000999')],
    'mccormick': [(7, 'M001218')],
}

check('unique surname resolves',
      resolve_bioguide('Michael A. Collins Jr', 'U.S. Representative — GA-10',
                       BY_SURNAME), 'C001129')
check('a Jr filer resolves',
      resolve_bioguide('Michael A. Collins Jr', 'GA-10', BY_SURNAME), 'C001129')
check('unique surname needs no office at all',
      resolve_bioguide('Richard Dean McCormick', '', BY_SURNAME), 'M001218')

# The reason district is not the primary key: upstream office data is wrong.
check('a WRONG office cannot mis-resolve a unique surname (Collins listed as GA-08)',
      resolve_bioguide('Michael A. Collins', 'U.S. Representative — GA-08',
                       BY_SURNAME), 'C001129')
check('an out-of-state office string is harmless (McCormick listed as NY-01)',
      resolve_bioguide('Richard Dean McCormick', 'U.S. Representative — NY-01',
                       BY_SURNAME), 'M001218')

check('ambiguous surname refuses rather than guessing',
      resolve_bioguide('Austin Scott', 'U.S. Representative', BY_SURNAME), None)
check('ambiguous surname resolves when the district disambiguates',
      resolve_bioguide('Austin Scott', 'GA-08', BY_SURNAME), 'S001189')
check('ambiguous surname with an unmatched district still refuses',
      resolve_bioguide('Austin Scott', 'GA-99', BY_SURNAME), None)
check('unknown member', resolve_bioguide('Nobody Here', '', BY_SURNAME), None)

print('\n=== every published member is self-consistent with its own trades ===')
with open(DATA, encoding='utf-8') as fh:
    published = json.load(fh)['byMember']

# The invariant the fix guarantees: the counters shown on a member card describe
# the trade list published alongside them — merged or not.
for name, m in published.items():
    d = derive_counters(m['trades'])
    for field in ('tradeCount', 'purchases', 'sales', 'lateFilings'):
        check(f'{name}: {field}', m[field], d[field])
    check(f'{name}: estVolume', round(m['estVolume'], 2), round(d['estVolume'], 2))

print("\n=== the merged member no longer carries one filer's counters ===")
collins = published.get('Michael A. Collins')
if collins:
    print(f"  tradeCount={collins['tradeCount']} purchases={collins['purchases']} "
          f"sales={collins['sales']} estVolume={collins['estVolume']:,.2f}")
    # The pre-fix values, published while the card already showed 42 trades.
    check('purchases is no longer the unmerged 18', collins['purchases'] != 18, True)
    check('sales is no longer the unmerged 5', collins['sales'] != 5, True)
    check('estVolume is no longer the unmerged 306,511.50',
          round(collins['estVolume'], 2) != 306511.50, True)

print('\n=== bioguide links point at the right person ===')
CURRENT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'assets', 'data', 'current-members.json')
with open(CURRENT, encoding='utf-8') as fh:
    delegation = {m['bioguideId']: m for m in json.load(fh)['members']}
for name, m in published.items():
    bid = m.get('bioguideId')
    if not bid:
        continue
    member = delegation.get(bid, {})
    check(f'{name} -> {member.get("lastName")}',
          (member.get('lastName') or '').lower(), filer_surname(name))

print('\n=== merge is idempotent under re-derivation ===')
merged = collins['trades'] + []            # same list, re-derived
check('re-deriving the same trades is stable',
      derive_counters(merged), derive_counters(collins['trades']))
check('empty trade list', derive_counters([]),
      {'tradeCount': 0, 'purchases': 0, 'sales': 0, 'lateFilings': 0, 'estVolume': 0})

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
sys.exit(1 if FAIL else 0)
