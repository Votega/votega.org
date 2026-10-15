#!/usr/bin/env python3
"""Compute per-legislator party-unity and participation scores for the GA
General Assembly, and publish them as a canonical, comparable dataset.

Two figures per member, the two most-requested legislator stats — published for
Congress by a dozen outlets, by nobody for Georgia:

  * **Party unity** — of the roll calls where a majority of the member's own
    party voted opposite a majority of the other party (a "party-line vote"),
    the share on which the member sided with their own caucus. This is the
    CQ/Voteview definition: it deliberately ignores lopsided, bipartisan, and
    unanimous votes, which say nothing about a member's independence.

  * **Participation** — of the passage roll calls held in the member's chamber
    while they were seated, the share on which they cast a Yea or Nay. "Other"
    (absent, excused, not voting, present) counts against it. This is a floor
    passage-vote participation rate, not attendance.

The methodology mirrors, one-for-one, the client-side computation that
ga-member.html already shows on a single member's page (buildPartyLoyaltySummary
/ buildParticipationSummary). The point of building it server-side is to make the
numbers canonical, stable, and *comparable across every member at once* — a
ranking nobody can produce from a single member page.

Input : assets/data/ga-member-votes.json, assets/data/ga-members.json
Output: assets/data/ga-party-unity.json

Usage:
  python scripts/generate_party_unity.py
  python scripts/generate_party_unity.py <votes.json> <members.json> <out.json>
"""

import json
import sys
from datetime import datetime, timezone

# scripts/ is sys.path[0] when run as `python scripts/generate_party_unity.py`
from lib.ga_voters import VOTING_CHAMBERS, DEPARTED_STATUSES, chamber_from_motion
from lib.votes_schema import member_votes_map
from lib.atomic_io import write_json_atomic
from lib.party_unity import OTHER_PARTY, score_participation, score_unity

VOTES_FILE = "assets/data/ga-member-votes.json"
MEMBERS_FILE = "assets/data/ga-members.json"
OUT_FILE = "assets/data/ga-party-unity.json"

#: A member with a near-full slate of roll calls but almost no Yea/Nay is a
#: presiding officer (the Speaker votes only to break ties by custom). Matches
#: the ga-member.html heuristic so both surfaces label them the same way rather
#: than reporting a misleadingly low participation rate.
PRESIDING_MIN_ROLLCALLS = 50
PRESIDING_MAX_VOTES = 3


def rollcall_key(vote_id):
    """Physical roll call a voteId belongs to. SOAP voteIds are '<rollCallId>-<billId>':
    one floor vote on a bundled calendar fans out into a record per bill, all with
    identical tallies. Scoring per voteId counted that one vote N times (2,418
    records vs ~1,520 real roll calls), so everything here keys on the prefix."""
    return str(vote_id).split("-", 1)[0]


def vote_chamber(meta):
    """Chamber a passage vote belongs to. Mirrors the client-side voteChamber() so
    server and page bucket votes identically.

    Prefers the chamber the producer recorded (generate_ga_votes_soap.py stores the
    Branch it fetched the roll call from) and only falls back to reading the motion
    text, which is reliable for the "agree to" family only, and inverted there — see
    chamber_from_motion().
    """
    meta = meta or {}
    return meta.get("chamber") or chamber_from_motion(meta.get("motionText"))


def build_party_vote_index(member_votes, party_map):
    """rollCallKey -> {party: {'yea': n, 'nay': n}} over every member's Yea/Nay votes.

    De-duplicates (roll call, member): bundled-bill records of one roll call
    collapse to a single count (see rollcall_key).
    """
    index = {}
    for voter_id, votes in member_votes.items():
        party = party_map.get(voter_id)
        if party not in OTHER_PARTY:  # only the two major caucuses define a party line
            continue
        seen = set()
        for entry in votes:
            vote = entry.get("vote")
            if vote not in ("Yea", "Nay"):
                continue
            vid = entry.get("voteId")
            if not vid:
                continue
            vid = rollcall_key(vid)
            if vid in seen:
                continue
            seen.add(vid)
            tally = index.setdefault(vid, {})
            pt = tally.setdefault(party, {"yea": 0, "nay": 0})
            pt["yea" if vote == "Yea" else "nay"] += 1
    return index


def member_scores(member, votes, votes_index, party_vote_index):
    """Compute participation and party-unity for one member.

    Returns a dict of the member's figures, or None if they have no roll calls
    in their own chamber (e.g. an executive or a member with no vote data).
    """
    chamber = member.get("chamber")
    party = member.get("party")

    # --- Participation: own-chamber roll calls, deduped by physical roll call ---
    seen = {}
    for entry in votes:
        vid = entry.get("voteId")
        if not vid:
            continue
        vc = vote_chamber(votes_index.get(vid))
        if chamber and vc and vc != chamber:
            continue  # own chamber only
        rc = rollcall_key(vid)
        if rc not in seen:
            seen[rc] = entry.get("vote")

    total_rollcalls, cast, missed = score_participation(seen)
    if total_rollcalls == 0:
        return None

    presiding = total_rollcalls >= PRESIDING_MIN_ROLLCALLS and cast <= PRESIDING_MAX_VOTES

    scores = {
        "totalRollCalls": total_rollcalls,
        "cast": cast,
        "missed": missed,
        # Participation and missed rate are complementary; publish both so a
        # consumer can rank on either without re-deriving.
        "participationRate": round(cast / total_rollcalls, 4),
        "missedRate": round(missed / total_rollcalls, 4),
        "presidingOfficer": presiding,
        "partyUnity": None,
        "partyLineVotes": 0,
        "votedWithParty": 0,
    }

    # --- Party unity: party-line roll calls only ---
    # The rule itself lives in lib/party_unity.py so the GA and federal
    # scorecards cannot drift to two definitions of "party-line vote".
    considered, aligned = score_unity(seen, party_vote_index, party)
    if considered > 0:
        scores["partyLineVotes"] = considered
        scores["votedWithParty"] = aligned
        scores["partyUnity"] = round(aligned / considered, 4)
        # Independence is the complement — the share of party-line votes on
        # which the member broke with their own caucus.
        scores["independenceRate"] = round(1 - aligned / considered, 4)

    return scores


def main():
    votes_path = sys.argv[1] if len(sys.argv) > 1 else VOTES_FILE
    members_path = sys.argv[2] if len(sys.argv) > 2 else MEMBERS_FILE
    out_path = sys.argv[3] if len(sys.argv) > 3 else OUT_FILE

    with open(votes_path, encoding="utf-8") as f:
        votes_data = json.load(f)
    with open(members_path, encoding="utf-8") as f:
        members_data = json.load(f)

    votes_index = votes_data.get("votes", {})
    # Decode compact or legacy memberVotes to the {pid: [{voteId, vote}]} shape the
    # rest of this script expects. See scripts/lib/votes_schema.py.
    member_votes = member_votes_map(votes_data)

    party_map = {
        m["id"]: m.get("party")
        for m in members_data.get("members", [])
        if m.get("id")
    }
    party_vote_index = build_party_vote_index(member_votes, party_map)

    results = []
    for m in members_data.get("members", []):
        mid = m.get("id")
        # Only legislators who still hold a seat in a voting chamber. Executives
        # and members who have left the seat (DEPARTED_STATUSES) are excluded from
        # a "current" comparison; a Suspended member keeps the seat and stays in.
        if not mid or m.get("chamber") not in VOTING_CHAMBERS or m.get("status") in DEPARTED_STATUSES:
            continue
        votes = member_votes.get(mid)
        if not votes:
            continue
        scores = member_scores(m, votes, votes_index, party_vote_index)
        if scores is None:
            continue
        results.append({
            "id": mid,
            "name": m.get("name"),
            "party": m.get("party"),
            "chamber": m.get("chamber"),
            "district": m.get("district"),
            **scores,
        })

    # Sort deterministically: chamber, then district, then name. Rankings are a
    # concern of the consumer (page / sibling repo), not the file order.
    results.sort(key=lambda r: (
        r["chamber"] or "",
        r["district"] if r["district"] is not None else 9999,
        r["name"] or "",
    ))

    scored = [r for r in results if r["partyUnity"] is not None]
    out = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Derived from ga-member-votes.json (legis.ga.gov SOAP roll calls)",
            "biennium": votes_data.get("metadata", {}).get("biennium"),
            "sessions": votes_data.get("metadata", {}).get("sessions", []),
            "paginationComplete": votes_data.get("metadata", {}).get("paginationComplete"),
            "count": len(results),
            "scoredForUnity": len(scored),
            "methodology": {
                "partyUnity": "Share of party-line roll calls (own-party majority opposite the other party's majority) on which the member voted with their own caucus. Excludes lopsided and bipartisan votes.",
                "participation": "Share of the member's own-chamber passage roll calls on which they cast a Yea or Nay; Other (absent/excused/not voting/present) counts against it.",
            },
        },
        "members": results,
    }

    write_json_atomic(out_path, out, indent=2)

    print(f"Wrote {out_path}: {len(results)} members ({len(scored)} with a party-unity score)")


if __name__ == "__main__":
    main()
