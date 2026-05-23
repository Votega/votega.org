#!/usr/bin/env python3
"""
set_general_candidates.py — promote candidates to the general election phase.

Usage:
  python scripts/set_general_candidates.py <race-id> <candidate-id> [<candidate-id> ...]

Examples:
  # Attorney General — Strickland (R) vs Miller (D)
  python scripts/set_general_candidates.py ga-attorney-general-2026 \
      challenger-robert-strickland-ag-2026 challenger-tanya-miller-ag-2026

  # U.S. Senate — after runoff settles
  python scripts/set_general_candidates.py senate-2026 \
      O000174 challenger-mike-collins-senate-2026

The script:
  1. Finds each candidate ID anywhere in the race's phases (primary, runoff, or general)
  2. Groups them by party into phases.general.ballots
  3. Sets activePhase to "general"
  4. Saves races.json

To add a candidate not already in any phase (e.g. a write-in or independent),
pass their full JSON on stdin instead — see --help for details.
"""

import json
import sys
import os

RACES_PATH = os.path.join(os.path.dirname(__file__), '..', 'assets', 'data', 'races.json')


def find_candidate(race, candidate_id):
    """Search all phases of a race for a candidate by id or memberId."""
    for phase_name, phase in race.get('phases', {}).items():
        # ballots format (keyed by party)
        for party, cands in phase.get('ballots', {}).items():
            for c in cands:
                if c.get('id') == candidate_id or c.get('memberId') == candidate_id:
                    return c
        # flat candidates array
        for c in phase.get('candidates', []):
            if c.get('id') == candidate_id or c.get('memberId') == candidate_id:
                return c
    return None


def candidate_party(candidate):
    """Best-effort party extraction from a candidate object."""
    p = candidate.get('party', '')
    if p:
        return p
    # Federal incumbents reference a memberId — label as Unknown until the
    # caller adds party info, but don't fail.
    return 'Unknown'


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)

    race_id       = sys.argv[1]
    candidate_ids = sys.argv[2:]

    with open(RACES_PATH, encoding='utf-8') as f:
        data = json.load(f)

    # Find the race
    race = next((r for r in data['races'] if r['id'] == race_id), None)
    if not race:
        print(f"ERROR: race '{race_id}' not found in races.json")
        print("Available IDs:", [r['id'] for r in data['races'] if r.get('cycle') == 2026])
        sys.exit(1)

    # Resolve each candidate
    resolved = []
    for cid in candidate_ids:
        c = find_candidate(race, cid)
        if not c:
            print(f"ERROR: candidate '{cid}' not found in any phase of race '{race_id}'")
            print("Tip: run  python scripts/set_general_candidates.py --list", race_id)
            sys.exit(1)
        resolved.append(c)

    # Group by party into ballots dict
    ballots = {}
    for c in resolved:
        party = candidate_party(c)
        ballots.setdefault(party, []).append(c)

    # Sort parties: Democrat first, then Republican, then others
    party_order = lambda p: 0 if 'democrat' in p.lower() else 1 if 'republican' in p.lower() else 2
    ballots = dict(sorted(ballots.items(), key=lambda kv: party_order(kv[0])))

    # Update the race
    race['activePhase'] = 'general'
    race['phases'].setdefault('general', {})['electionDate'] = race['phases'].get('general', {}).get('electionDate', '2026-11-03')
    race['phases']['general']['ballots'] = ballots
    # Remove the old empty candidates list if present
    race['phases']['general'].pop('candidates', None)

    with open(RACES_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Updated '{race_id}' -> activePhase: general")
    for party, cands in ballots.items():
        for c in cands:
            name = c.get('name') or c.get('memberId', '(incumbent ref)')
            print(f"  [{party}] {name}")
    print("races.json saved.")


# --list helper: show all candidate IDs in a race
if '--list' in sys.argv:
    race_id = sys.argv[sys.argv.index('--list') + 1]
    with open(RACES_PATH, encoding='utf-8') as f:
        data = json.load(f)
    race = next((r for r in data['races'] if r['id'] == race_id), None)
    if not race:
        print(f"Race '{race_id}' not found.")
        sys.exit(1)
    print(f"Candidates in '{race_id}':")
    for phase_name, phase in race['phases'].items():
        for party, cands in phase.get('ballots', {}).items():
            for c in cands:
                cid = c.get('id') or c.get('memberId', '?')
                print(f"  [{phase_name} / {party}] {cid}  —  {c.get('name', '(incumbent ref)')}")
        for c in phase.get('candidates', []):
            cid = c.get('id') or c.get('memberId', '?')
            print(f"  [{phase_name}] {cid}  —  {c.get('name', '')}")
    sys.exit(0)


if __name__ == '__main__':
    main()
