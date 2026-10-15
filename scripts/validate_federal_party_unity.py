#!/usr/bin/env python3
"""Structural checks on the federal party-unity scorecard, before it is committed.

CLAUDE.md's rule is "never commit based on JSON validity alone". That matters more
here than for most artifacts: this file states, as fact, how loyal a named member
of Congress is to their party. An artifact whose rates had drifted above 1, whose
aligned count exceeded its own denominator, or that had quietly lost a member is
still valid JSON of about the right size, and would publish as confidently as a
correct one.

The checks are all impossibility checks - things that cannot be true of any real
member - rather than thresholds, so they need no tuning as the record grows and
cannot go slack:

  * every rate within 0..1;
  * votedWithParty <= partyLineVotes (you cannot side with your caucus more often
    than there were chances to);
  * cast <= totalRollCalls;
  * no member scored against more roll calls than their chamber actually held;
  * every sitting Georgia roster member present.

Usage:
    python scripts/validate_federal_party_unity.py \\
        assets/data/federal-party-unity.json \\
        assets/data/federal-member-votes.json \\
        assets/data/current-members.json

Exit 0 when every check passes, 1 otherwise (the caller must not commit).
"""

import json
import sys

#: Fields that are shares and must therefore lie in 0..1, or be null.
RATE_FIELDS = ("participationRate", "missedRate", "partyUnity", "independenceRate")


def problems(scorecard, votes_data, members_data):
    """Every violation found, as readable strings. Empty list means the file is sane."""
    found = []
    members = scorecard.get("members") or {}
    if not members:
        return ["scorecard has no members"]

    # How many roll calls each chamber actually held, as the ceiling on any
    # member's denominator.
    held = {}
    for meta in (votes_data.get("votes") or {}).values():
        chamber = (meta or {}).get("chamber")
        if chamber:
            held[chamber] = held.get(chamber, 0) + 1

    for bioguide, entry in sorted(members.items()):
        for field in RATE_FIELDS:
            value = entry.get(field)
            if value is None:
                continue
            if not 0 <= value <= 1:
                found.append(f"{bioguide}: {field} is {value}, outside 0..1")

        party_line = entry.get("partyLineVotes") or 0
        aligned = entry.get("votedWithParty") or 0
        if aligned > party_line:
            found.append(f"{bioguide}: votedWithParty {aligned} exceeds "
                         f"partyLineVotes {party_line}")

        total = entry.get("totalRollCalls") or 0
        cast = entry.get("cast") or 0
        if cast > total:
            found.append(f"{bioguide}: cast {cast} exceeds totalRollCalls {total}")

        ceiling = held.get(entry.get("chamber"))
        if ceiling is not None and total > ceiling:
            found.append(f"{bioguide}: scored against {total} roll calls but the "
                         f"{entry.get('chamber')} held only {ceiling}")

    # A member who silently vanished from the scorecard reads on the site as a
    # member with no record, which is a different claim from the truth.
    roster = {m.get("bioguideId") for m in (members_data.get("members") or [])
              if m.get("state") == "Georgia" and m.get("bioguideId")}
    for bioguide in sorted(roster - set(members)):
        found.append(f"{bioguide}: sitting Georgia member missing from the scorecard")

    return found


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    scorecard_path, votes_path, members_path = sys.argv[1:4]

    try:
        with open(scorecard_path, encoding="utf-8") as fh:
            scorecard = json.load(fh)
        with open(votes_path, encoding="utf-8") as fh:
            votes_data = json.load(fh)
        with open(members_path, encoding="utf-8") as fh:
            members_data = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.exit(f"FAIL: cannot read inputs: {exc}")

    found = problems(scorecard, votes_data, members_data)

    meta = scorecard.get("metadata") or {}
    print(f"note: {meta.get('count')} members, "
          f"{meta.get('scoredForUnity')} with a party-unity score, "
          f"{meta.get('withVotesButNotInRoster')} with votes but no roster entry")

    if found:
        print("")
        for line in found:
            print(f"FAIL: {line}")
        return 1
    print("\nAll federal party-unity checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
