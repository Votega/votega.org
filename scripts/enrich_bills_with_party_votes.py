#!/usr/bin/env python3
"""
Enrich ga-bills.json passageVotes with party tallies.
Joins ga-member-votes.json (individual votes) with ga-members.json (party) and
injects a partyTally field into each passageVote entry in ga-bills.json.

Usage:
  python scripts/enrich_bills_with_party_votes.py \
    assets/data/ga-bills.json \
    assets/data/ga-member-votes.json \
    assets/data/ga-members.json
"""

import json
import sys
from datetime import datetime, timezone

# scripts/ is sys.path[0] when run as `python scripts/enrich_bills_with_party_votes.py`
from lib.votes_schema import member_votes_map
from lib.atomic_io import write_json_atomic
from lib.ga_passage import normalize_bill


def _rollcall_key(bill, date, yea, nay, motion_text=""):
    """Join key for a single roll call: normalized bill identifier, ISO date, the
    yea/nay tally and the official caption ("PASSAGE", "Local Calendar", …).

    History: this once keyed on (bill, motionText), which broke when the votes moved
    off Open States (OS phrased motions "House Vote #N …"), so it was relaxed to
    (bill, date, yea, nay). That is ambiguous: SB 76 on 2026-04-02 has a PASSAGE and an
    "Agree to Senate Amend to House Sub" roll call that both ended 168-2 with rosters
    twelve members apart, and a plain dict kept whichever came last. Both files now come
    from the same legis.ga.gov caption, so the caption is back in the key; it separates
    9 of the 18 colliding pairs. What still collides (a calendar voted twice the same day
    at the same tally) is handled in resolve_vote_id."""
    return (normalize_bill(bill), (date or "")[:10], yea, nay, (motion_text or "").strip().lower())


def resolve_vote_id(candidates, tally_for):
    """Pick the voteId whose roster belongs to a passage vote, or None if it is unsafe.

    `candidates` are the voteIds sharing a key. One candidate is the normal case. With
    several, the roll calls are indistinguishable by anything the bills file carries, so
    use their roster only if every candidate yields the SAME party tally (then it is
    right whichever one this is); otherwise return None and leave the vote without a
    party tally, which the UI already handles, rather than attach another roll call's."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    tallies = [tally_for(c) for c in candidates]
    return candidates[0] if all(t == tallies[0] for t in tallies[1:]) else None


def main():
    if len(sys.argv) < 4:
        print("Usage: enrich_bills_with_party_votes.py <ga-bills.json> <ga-member-votes.json> <ga-members.json>")
        sys.exit(1)

    bills_path   = sys.argv[1]
    votes_path   = sys.argv[2]
    members_path = sys.argv[3]

    # 1. Build party_map: {ocd-person-id: party}
    with open(members_path, encoding='utf-8') as f:
        members_data = json.load(f)
    party_map = {m['id']: m['party'] for m in members_data.get('members', []) if m.get('id') and m.get('party')}
    print(f"Loaded {len(party_map)} members with party data")

    # 2. Load ga-member-votes.json
    with open(votes_path, encoding='utf-8') as f:
        votes_data = json.load(f)

    # Build vote_index: {rollcall key: [voteId, ...]}. See _rollcall_key / resolve_vote_id.
    vote_index = {}
    vote_vacant = {}
    for vote_id, v in votes_data.get('votes', {}).items():
        key = _rollcall_key(v.get('bill', ''), v.get('date', ''), v.get('yea'), v.get('nay'),
                            v.get('motionText', ''))
        vote_index.setdefault(key, []).append(vote_id)
        vote_vacant[vote_id] = v.get('vacant', 0) or 0

    # Invert memberVotes into vote_roster: {voteId: {personId: vote_option}}.
    # member_votes_map decodes compact or legacy schema; see scripts/lib/votes_schema.py.
    vote_roster = {}
    for person_id, person_votes in member_votes_map(votes_data).items():
        for entry in person_votes:
            vid = entry.get('voteId')
            if vid:
                vote_roster.setdefault(vid, {})[person_id] = entry.get('vote', '')

    print(f"Loaded {len(vote_index)} vote events, {len(vote_roster)} vote rosters")

    # 3. Load and enrich ga-bills.json
    with open(bills_path, encoding='utf-8') as f:
        bills_data = json.load(f)

    VOTE_MAP = {
        'Yea':        'yea',
        'Nay':        'nay',
        'Not Voting': 'other',
        'Present':    'other',
        'Absent':     'other',
        'Excused':    'other',
        'Other':      'other',
    }
    PARTIES = ('Republican', 'Democratic', 'Independent')

    def tally_for(vote_id):
        tally = {p: {'yea': 0, 'nay': 0, 'other': 0} for p in PARTIES}
        for person_id, vote_option in vote_roster.get(vote_id, {}).items():
            party = party_map.get(person_id)
            if party and party in tally:
                tally[party][VOTE_MAP.get(vote_option, 'other')] += 1
        return tally

    matched = 0
    unmatched = 0
    ambiguous = 0

    for bill in bills_data.get('bills', []):
        identifier = bill.get('identifier', '')
        for pv in bill.get('passageVotes', []):
            key = _rollcall_key(identifier, pv.get('date', ''), pv.get('yea'), pv.get('nay'),
                                pv.get('motionText', ''))
            candidates = vote_index.get(key, [])
            vote_id = resolve_vote_id(candidates, lambda c: tally_for(c))
            if not vote_id:
                if candidates:
                    ambiguous += 1   # several indistinguishable roll calls, rosters differ
                else:
                    unmatched += 1
                # A stale tally from a previous run must not outlive a failed match.
                for stale in ('partyTally', 'partyTallyCoverage', 'partyTallyTallied', 'partyTallyOfficial'):
                    pv.pop(stale, None)
                continue

            tally = tally_for(vote_id)

            # Only include parties that cast at least one vote
            pv['partyTally'] = {
                p: counts for p, counts in tally.items()
                if counts['yea'] + counts['nay'] + counts['other'] > 0
            }

            # voter.id resolution failures in generate_ga_votes_data.py (common on
            # surname collisions) mean the roster this tally is built from can be
            # short of the official yea/nay/other totals reported alongside it.
            # Surface that gap explicitly so the UI can hedge or suppress the
            # party-line badge instead of presenting a partial count as complete.
            # The official totals count every seat (House 180, Senate 56), but an empty
            # seat has no member to attribute. The votes file records those per roll
            # call as `vacant`; leaving them in made a complete roster read as ~97%
            # covered and hedged the party-line badge on roughly half of all votes.
            official_total = (pv.get('yea', 0) + pv.get('nay', 0) + pv.get('other', 0)
                              - vote_vacant.get(vote_id, 0))
            tallied_total = sum(
                counts['yea'] + counts['nay'] + counts['other']
                for counts in tally.values()
            )
            pv['partyTallyCoverage'] = (
                round(tallied_total / official_total, 4) if official_total else None
            )
            # Exact counts as well as the ratio. The UI needs to know how many
            # votes are *unaccounted for* to decide whether a party-line call is
            # safe -- a party's direction only flips if the missing votes could
            # outweigh its margin -- and reconstructing that from a rounded
            # coverage ratio loses the precision the comparison depends on.
            # See CODEBASE-REVIEW-2026-08-18.md finding 3.4.
            pv['partyTallyTallied'] = tallied_total
            pv['partyTallyOfficial'] = official_total
            matched += 1

    # Update metadata timestamp
    if 'metadata' in bills_data:
        bills_data['metadata']['partyTallyEnrichedAt'] = datetime.now(timezone.utc).isoformat()

    # 4. Write enriched ga-bills.json
    # Minified to match generate_ga_bills_data.py's own output: this is the FINAL
    # writer (it runs after generate in update-ga-bills.yml), so an indent=2 here
    # was what left the committed file pretty-printed at ~9 MB. It is a large,
    # generated, client-fetched blob, not a human-reviewed diff.
    write_json_atomic(bills_path, bills_data, separators=(',', ':'))

    print(f"Done — {matched} passageVotes enriched, {unmatched} unmatched, "
          f"{ambiguous} skipped as ambiguous")
    print(f"Written: {bills_path}")


if __name__ == '__main__':
    main()
