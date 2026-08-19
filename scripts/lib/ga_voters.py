#!/usr/bin/env python3
"""Resolve an Open States roll-call voter to a GA legislator in ga-members.json.

Both GA vote generators join roll-call rows to `ga-members.json` by OCD person
id, and both hit the same three failure modes:

  1. `voter.id` is **absent** — Open States most often fails to resolve it on a
     surname collision (Georgia seats five Joneses, four Smiths, four Jacksons).
  2. `voter.id` is **present but stale** — it points at a deprecated or duplicate
     Open States person record that no longer appears in `ga-members.json`. This
     is the harder case, because the id looks perfectly valid.
  3. Neither an id nor a usable name is available.

Case 2 is what CODEBASE-REVIEW-2026-08-18.md finding 1.5 describes: 21 such
"ghost" ids across the 9 curated bills left **38 of 232 sitting legislators**
with no key votes at all — and the name fallback that would have caught them was
gated on `if not voter_id`, so a present-but-unresolvable id sailed straight past
it. The fix is to trigger the fallback on *unresolvable*, not on *missing*.

Consolidating here also removes a fork: `generate_ga_votes_data.py` had the name
index, chamber inference and legacy-id map; `generate_curated_ga_bills.py` had
none of them and keyed `memberVotes` on the raw `voter.id` with no validation.

Import from a generator in scripts/ (sys.path[0] is scripts/ when run as
`python scripts/generate_x.py`):

    from lib.ga_voters import MemberIndex, resolve_voter
"""

import json
import re

MEMBERS_FILE = "assets/data/ga-members.json"

#: Chambers whose members actually cast roll-call votes. `ga-members.json` also
#: carries an `executive` chamber (Governor, Lt. Governor, AG, SoS), which must
#: never be treated as a missing voter.
VOTING_CHAMBERS = ("Senate", "House of Representatives")

#: Deprecated OCD person ids folded into the member's current id. Open States
#: occasionally re-issues a person a new id mid-session, stranding their earlier
#: votes under the old one. Identified 2026-07-24 by LegiScan roll-call
#: cross-reference: identical Yea/Nay/Other pattern across every roll call shared
#: with the current id (both are Speaker Jon Burns; by House custom a presiding
#: officer votes only to break ties, so both ids show ~100% "Other").
#:
#: Only add an entry with that level of evidence. A wrong alias silently
#: attributes one legislator's votes to another.
LEGACY_PERSON_ID_MAP = {
    'ocd-person/4161e949-6ea2-4df9-8248-cabcf40286ae': 'ocd-person/64012657-d026-411c-9525-3232524a5145',  # Jon Burns
}

_TITLE_PREFIX_RE = re.compile(
    r'^(rep(resentative)?|sen(ator)?|mr|mrs|ms|dr)\.?\s+', re.IGNORECASE
)


def normalize_voter_name(name):
    """Fold a name to a loose comparison key.

    Strips a leading title, reorders "Last, First" to "First Last", drops
    punctuation and extra whitespace, lowercases the rest. Open States'
    `voter_name` is a raw string scraped from the legislature's site and its
    convention is not guaranteed to match ga-members.json's "First Last".
    """
    if not name:
        return ''
    name = _TITLE_PREFIX_RE.sub('', name.strip())
    if ',' in name:
        last, _, first = name.partition(',')
        name = f'{first.strip()} {last.strip()}'
    name = re.sub(r"[.,]", '', name)
    return re.sub(r'\s+', ' ', name).strip().lower()


def event_chamber(motion_text, organization=None):
    """Which chamber held a roll call: 'Senate', 'House of Representatives', or None."""
    cls = (organization or {}).get('classification')
    if cls == 'upper':
        return 'Senate'
    if cls == 'lower':
        return 'House of Representatives'
    mt = motion_text or ''
    if 'Senate' in mt:
        return 'Senate'
    if 'House' in mt:
        return 'House of Representatives'
    return None


class MemberIndex:
    """Lookups over ga-members.json needed to resolve a roll-call voter."""

    def __init__(self, path=MEMBERS_FILE):
        self.by_id = {}
        self.chambers = {}
        self.parties = {}
        self.by_name = {}
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return

        for m in data.get('members', []):
            mid = m.get('id')
            if not mid:
                continue
            self.by_id[mid] = m
            self.chambers[mid] = m.get('chamber')
            self.parties[mid] = m.get('party')

            chamber, name = m.get('chamber'), normalize_voter_name(m.get('name'))
            if not chamber or not name:
                continue
            key = (chamber, name)
            # A (chamber, name) matching more than one member maps to None: an
            # ambiguous name is not safe to attribute either way, so it is
            # treated as unresolved rather than guessed.
            self.by_name[key] = None if key in self.by_name else mid

    def __bool__(self):
        return bool(self.by_id)

    def __len__(self):
        return len(self.by_id)


def resolve_voter(voter_id, voter_name, chamber, index):
    """Resolve one roll-call row to a member id.

    Returns `(member_id, how)` where `how` is one of:

        'id'      resolved directly by OCD person id
        'alias'   a known deprecated id, folded into the current one
        'name'    id was missing or unresolvable; matched on (chamber, name)
        'ghost'   id present, not in ga-members.json, and no name match
        'unresolved'  no usable id and no name match

    Only 'id', 'alias' and 'name' carry a member id; the rest return None. The
    caller should count every outcome so a regression is visible in metadata
    rather than silently shrinking the roster.
    """
    if not index:
        # No member data to validate against — trust the id rather than
        # discarding every vote (matches the previous behaviour).
        return (voter_id, 'id') if voter_id else (None, 'unresolved')

    canonical = LEGACY_PERSON_ID_MAP.get(voter_id, voter_id)
    if canonical and canonical in index.by_id:
        return canonical, ('alias' if canonical != voter_id else 'id')

    # Either no id at all, or an id pointing at a person ga-members.json does not
    # know. Both are recoverable from the name within the roll call's chamber —
    # gating this on "no id" alone is what let 21 ghost ids orphan 38 members.
    if chamber and voter_name:
        matched = index.by_name.get((chamber, normalize_voter_name(voter_name)))
        if matched:
            return matched, 'name'

    return None, ('ghost' if voter_id else 'unresolved')


_SUFFIX_RE = re.compile(r'\b(jr|sr|ii|iii|iv|v)\b\.?$', re.IGNORECASE)


def surname_key(name):
    """Last name of a person, folded for comparison.

    Georgia roll calls identify voters by surname alone ("JONES"), while
    ga-members.json carries full names ("Jan Jones"), so this is the only field
    the two share.
    """
    n = normalize_voter_name(name)
    n = _SUFFIX_RE.sub('', n).strip()
    parts = n.split()
    return parts[-1] if parts else ''


def assign_remaining_by_surname(pending, resolved_ids, chamber, index):
    """Resolve surname-only rows by elimination against the chamber's roster.

    Open States supplies `voter_name` as a bare surname and omits `voter.id`
    exactly when that surname is shared — so the rows that need help are the ones
    a name lookup can never settle on its own. What makes them recoverable is
    that a roll call lists **every seat**: a 2025-26 House vote has 180 rows, of
    which 154 resolve by id, leaving 26 rows that must be the 26 sitting members
    not yet accounted for.

    Two conditions must both hold before anything is attributed, because the cost
    of being wrong is publishing a false voting record for a named legislator:

      1. The number of unresolved rows carrying a surname equals the number of
         still-unassigned sitting members with that surname. Any imbalance means
         someone in the group is unaccounted for, so the pairing is guesswork.
      2. Every one of those rows recorded the *same* option. Then it does not
         matter which row belongs to which member — they all voted alike, so the
         result is identical under any pairing. If they split, the data cannot say
         who voted which way and the whole group is left unresolved.

    `pending` is a list of `(row_key, voter_name, option)`. Returns
    `(assignments, unresolved_keys)` where assignments maps row_key -> member id.
    """
    assignments, unresolved = {}, []
    if not index or not chamber:
        return assignments, [k for k, _, _ in pending]

    seated = [m for m in index.by_id.values()
              if m.get('chamber') == chamber and not m.get('status')]
    available = {}
    for m in seated:
        if m['id'] not in resolved_ids:
            available.setdefault(surname_key(m.get('name')), []).append(m['id'])

    groups = {}
    for key, name, option in pending:
        groups.setdefault(surname_key(name), []).append((key, option))

    for sn, rows in groups.items():
        candidates = available.get(sn, [])
        options = {opt for _, opt in rows}
        if candidates and len(candidates) == len(rows) and len(options) == 1:
            for (key, _), member_id in zip(rows, candidates):
                assignments[key] = member_id
        else:
            unresolved.extend(key for key, _ in rows)

    return assignments, unresolved


def new_stats():
    """Counter dict for the outcomes of resolve_voter()."""
    return {'id': 0, 'alias': 0, 'name': 0, 'surname': 0, 'ghost': 0, 'unresolved': 0}


def summarize(stats):
    """One-line human summary of a stats dict."""
    return (f"resolved {stats['id']} by id, {stats['alias']} via alias, "
            f"{stats['name']} by name, {stats.get('surname', 0)} by surname elimination; "
            f"{stats['ghost']} ghost id(s), {stats['unresolved']} unresolved row(s)")
