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
from lib.ga_voters import VOTING_CHAMBERS

VOTES_FILE = "assets/data/ga-member-votes.json"
MEMBERS_FILE = "assets/data/ga-members.json"
OUT_FILE = "assets/data/ga-party-unity.json"

OTHER_PARTY = {"Democratic": "Republican", "Republican": "Democratic"}

#: A member with a near-full slate of roll calls but almost no Yea/Nay is a
#: presiding officer (the Speaker votes only to break ties by custom). Matches
#: the ga-member.html heuristic so both surfaces label them the same way rather
#: than reporting a misleadingly low participation rate.
PRESIDING_MIN_ROLLCALLS = 50
PRESIDING_MAX_VOTES = 3


def vote_chamber(meta):
    """Chamber a passage vote belongs to, from its motion text. Mirrors the
    client-side voteChamber() so server and page bucket votes identically."""
    mt = (meta or {}).get("motionText", "") or ""
    if "Senate" in mt:
        return "Senate"
    if "House" in mt:
        return "House of Representatives"
    return ""


def build_party_vote_index(member_votes, party_map):
    """voteId -> {party: {'yea': n, 'nay': n}} over every member's Yea/Nay votes.

    De-duplicates (voteId, member) defensively; the generator upstream already
    enforces one row per member per vote, so this is normally a no-op.
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
            if not vid or vid in seen:
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

    # --- Participation: own-chamber roll calls, deduped by voteId ---
    seen = {}
    for entry in votes:
        vid = entry.get("voteId")
        if not vid:
            continue
        vc = vote_chamber(votes_index.get(vid))
        if chamber and vc and vc != chamber:
            continue  # own chamber only
        if vid not in seen:
            seen[vid] = entry.get("vote")

    total_rollcalls = len(seen)
    if total_rollcalls == 0:
        return None

    cast = sum(1 for v in seen.values() if v in ("Yea", "Nay"))
    missed = total_rollcalls - cast
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
    other_party = OTHER_PARTY.get(party)
    if other_party:
        aligned = 0
        considered = 0
        for vid, vote in seen.items():
            if vote not in ("Yea", "Nay"):
                continue
            tally = party_vote_index.get(vid)
            if not tally:
                continue
            own = tally.get(party)
            opp = tally.get(other_party)
            if not own or not opp:
                continue
            # Need at least one OTHER same-party voter, and a non-tied majority
            # in each caucus, else "the party's position" is undefined.
            if own["yea"] + own["nay"] < 2 or own["yea"] == own["nay"]:
                continue
            if opp["yea"] + opp["nay"] == 0 or opp["yea"] == opp["nay"]:
                continue
            own_dir = "Yea" if own["yea"] > own["nay"] else "Nay"
            opp_dir = "Yea" if opp["yea"] > opp["nay"] else "Nay"
            if own_dir == opp_dir:
                continue  # both caucuses agreed — not a party-line vote
            considered += 1
            if vote == own_dir:
                aligned += 1

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
    member_votes = votes_data.get("memberVotes", {})

    party_map = {
        m["id"]: m.get("party")
        for m in members_data.get("members", [])
        if m.get("id")
    }
    party_vote_index = build_party_vote_index(member_votes, party_map)

    results = []
    for m in members_data.get("members", []):
        mid = m.get("id")
        # Only sitting legislators of a voting chamber. Executives, and members
        # who have left the seat, are excluded from a "current" comparison — the
        # same filter ga.js and the majority tracker apply.
        if not mid or m.get("chamber") not in VOTING_CHAMBERS or m.get("status"):
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
            "source": "Derived from ga-member-votes.json (Open States API roll calls)",
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

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Wrote {out_path}: {len(results)} members ({len(scored)} with a party-unity score)")


if __name__ == "__main__":
    main()
