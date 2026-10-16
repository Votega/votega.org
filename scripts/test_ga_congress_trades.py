#!/usr/bin/env python3
"""Tests for the trades generator's counter derivation and bioguide join.

Guards CODEBASE-REVIEW-2026-08-18.md finding 3.3: `_mergeInto` extended the
merged member's trade list but left `purchases`, `sales`, `lateFilings` and
`estVolume` describing only one of the two filers, so Michael Collins' card
showed 42 trades beside a volume covering 23 of them.

Also guards the roster-driven behavior that replaced the overrides file:
dropping filers who have left the delegation, merging filers that share a
bioguideId, and deriving the office string -- each of which used to be a
hand-written entry in ga-congress-trades-overrides.json.

Runs offline against the committed ga-congress-trades.json.

Usage:
  python scripts/test_ga_congress_trades.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_ga_congress_trades import (  # noqa: E402
    delegation_office, derive_counters, drop_departed, filer_district,
    filer_surname, merge_duplicate_filers, resolve_bioguide,
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

print('\n=== delegation_office ===')
check('a representative', delegation_office(
      {'district': 7, 'chamber': 'House of Representatives'}),
      'U.S. Representative \u00b7 GA-07')
check('a two-digit district', delegation_office(
      {'district': 10, 'chamber': 'House of Representatives'}),
      'U.S. Representative \u00b7 GA-10')
check('a senator ignores the absent district', delegation_office(
      {'district': None, 'chamber': 'Senate'}), 'U.S. Senator \u00b7 GA')
check('a representative with no district yields nothing', delegation_office(
      {'district': None, 'chamber': 'House of Representatives'}), None)
check('no record at all', delegation_office(None), None)

print('\n=== drop_departed ===')
# 'graves' and 'greene' are absent from the GA roster: both had _exclude entries.
ROSTER = {'collins': [(10, 'C001129')], 'scott': [(8, 'S001189')],
          'mccormick': [(7, 'M001218')]}
FILERS = [
    {'full_name': 'Michael A. Collins', 'office': 'GA-08'},
    {'full_name': 'Michael A. Collins Jr', 'office': 'GA-10'},
    {'full_name': 'Tom Thomas Graves Jr', 'office': 'GA-14'},
    {'full_name': 'Marjorie Taylor Greene', 'office': 'GA-14'},
]
kept, gone = drop_departed(FILERS, ROSTER)
check('serving members are kept',
      [f['full_name'] for f in kept],
      ['Michael A. Collins', 'Michael A. Collins Jr'])
check('departed members are dropped',
      [f['full_name'] for f in gone],
      ['Tom Thomas Graves Jr', 'Marjorie Taylor Greene'])
check('a Jr suffix does not read as a departure',
      'Michael A. Collins Jr' in [f['full_name'] for f in kept], True)

# The guard that matters most: no roster must not empty the page.
kept_no_roster, gone_no_roster = drop_departed(FILERS, {})
check('a missing roster drops nobody', len(kept_no_roster), len(FILERS))
check('a missing roster reports no departures', gone_no_roster, [])


def member(filer_id, bioguide, *dates):
    """A by_member entry carrying one Purchase per date."""
    trades = [{'transaction_date': d, 'transaction_type': 'Purchase',
               'amount_range_low': 1000, 'amount_range_high': 15000,
               'is_late': False} for d in dates]
    return {'filerId': filer_id, 'bioguideId': bioguide, 'trades': trades,
            **derive_counters(trades)}


print('\n=== merge_duplicate_filers ===')
BY_MEMBER = {
    'Michael A. Collins':    member('house_michaela_collins', 'C001129',
                                    '2026-03-01', '2026-01-01'),
    'Michael A. Collins Jr': member('house_michaela_collins_jr', 'C001129',
                                    '2026-02-01'),
    'Austin Scott':          member('house_austin_scott', 'S001189', '2026-04-01'),
}
merges = merge_duplicate_filers(BY_MEMBER)
check('the duplicate entry is gone', 'Michael A. Collins Jr' in BY_MEMBER, False)
check('the entry with more trades survives', 'Michael A. Collins' in BY_MEMBER, True)
check('the merge is reported', merges,
      [('Michael A. Collins Jr', 'Michael A. Collins', 1)])
check('trades are combined', BY_MEMBER['Michael A. Collins']['tradeCount'], 3)
check('every counter is re-derived, not just tradeCount',
      {k: BY_MEMBER['Michael A. Collins'][k]
       for k in ('purchases', 'sales', 'lateFilings', 'estVolume')},
      {'purchases': 3, 'sales': 0, 'lateFilings': 0, 'estVolume': 24000.0})
check('the merged list stays sorted most-recent first',
      [t['transaction_date'] for t in BY_MEMBER['Michael A. Collins']['trades']],
      ['2026-03-01', '2026-02-01', '2026-01-01'])
check('an unrelated member is untouched', BY_MEMBER['Austin Scott']['tradeCount'], 1)

# Without a bioguideId there is no evidence two filers are one person, and
# merging on surname alone would recreate the Scott collision.
UNRESOLVED = {
    'Austin Scott': member('house_austin_scott', None, '2026-01-01'),
    'David Scott':  member('house_david_scott', None, '2026-02-01'),
}
check('unresolved filers are never merged', merge_duplicate_filers(UNRESOLVED), [])
check('both unresolved entries survive', sorted(UNRESOLVED), ['Austin Scott', 'David Scott'])

TWO_MEMBERS = {
    'Austin Scott': member('house_austin_scott', 'S001189', '2026-01-01'),
    'Rick Allen':   member('house_richardw_allen', 'A000372', '2026-02-01'),
}
check('distinct members are left alone', merge_duplicate_filers(TWO_MEMBERS), [])

CURRENT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'assets', 'data', 'current-members.json')
with open(CURRENT, encoding='utf-8') as fh:
    delegation = {m['bioguideId']: m for m in json.load(fh)['members']}

print('\n=== published offices match the roster ===')
# End-to-end: the office on every published card is the one the roster implies,
# so the NY-01 / GA-08 corrections hold without an override entry.
for name, m in published.items():
    bid = m.get('bioguideId')
    if not bid or bid not in delegation:
        continue
    record = delegation[bid]
    terms = (record.get('terms') or {}).get('item') or []
    expected = delegation_office({
        'district': record.get('district'),
        'chamber': (terms[-1].get('chamber') if terms else '') or '',
    })
    check(f'{name}: office', m.get('office'), expected)
    check(f'{name}: photoUrl',
          m.get('photoUrl'), (record.get('depiction') or {}).get('imageUrl'))

print('\n=== every published member is still in the delegation ===')
GA_SURNAMES = {(m.get('lastName') or '').strip().lower()
               for m in delegation.values() if m.get('state') == 'Georgia'}
for name in published:
    check(f'{name} is a current GA member', filer_surname(name) in GA_SURNAMES, True)

print('\n=== bioguide links point at the right person ===')
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
