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

    # Build vote_index: {(bill_identifier, motionText): voteId}
    vote_index = {}
    for vote_id, v in votes_data.get('votes', {}).items():
        key = (v.get('bill', ''), v.get('motionText', ''))
        vote_index[key] = vote_id

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

    matched = 0
    unmatched = 0

    for bill in bills_data.get('bills', []):
        identifier = bill.get('identifier', '')
        for pv in bill.get('passageVotes', []):
            key = (identifier, pv.get('motionText', ''))
            vote_id = vote_index.get(key)
            if not vote_id:
                unmatched += 1
                continue

            roster = vote_roster.get(vote_id, {})
            tally = {p: {'yea': 0, 'nay': 0, 'other': 0} for p in PARTIES}

            for person_id, vote_option in roster.items():
                party = party_map.get(person_id)
                if party and party in tally:
                    bucket = VOTE_MAP.get(vote_option, 'other')
                    tally[party][bucket] += 1

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
            official_total = pv.get('yea', 0) + pv.get('nay', 0) + pv.get('other', 0)
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
    with open(bills_path, 'w', encoding='utf-8') as f:
        json.dump(bills_data, f, separators=(',', ':'), ensure_ascii=False)

    print(f"Done — {matched} passageVotes enriched, {unmatched} unmatched")
    print(f"Written: {bills_path}")


if __name__ == '__main__':
    main()
