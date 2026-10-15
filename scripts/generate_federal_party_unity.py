#!/usr/bin/env python3
"""Party-unity and participation scores for Georgia's congressional delegation.

The federal counterpart to generate_party_unity.py, which does this for the
General Assembly. Both call the same rule (lib/party_unity.py), so "party-line
vote" means one thing across the site.

  * **Party unity** - of the roll calls where a majority of the member's own party
    voted opposite a majority of the other party, the share on which the member
    sided with their own caucus. The CQ/Voteview definition: lopsided, bipartisan
    and unanimous votes are ignored, because they say nothing about independence.

  * **Participation** - of the roll calls held in the member's chamber while they
    were seated, the share on which they cast a Yea or Nay. "Other" (not voting,
    present, absent, excused) counts against it. A floor-vote rate, not attendance.

**This could not be built until 2026-10-14.** federal-member-votes.json used to
hold only roll calls attached to bills that became law - 216 of 1,591, 13.6% of
the universe - which gave a House member a party-line denominator of 42. That
sample was also BIASED, not merely small: on it Carter read 100.0% unity against
98.9% on the full record, and Ossoff 91.5% against 96.0%. A scorecard built on it
would have published wrong numbers with every appearance of precision.

Input : assets/data/federal-member-votes.json, assets/data/current-members.json
Output: assets/data/federal-party-unity.json

Usage:
  python scripts/generate_federal_party_unity.py
  python scripts/generate_federal_party_unity.py <votes.json> <members.json> <out.json>
"""

import json
import sys
from datetime import datetime, timezone

# scripts/ is sys.path[0] when run as `python scripts/generate_federal_party_unity.py`
from lib.atomic_io import write_json_atomic
from lib.party_unity import (ABSTENTIONS, OTHER_PARTY, score_participation,
                             score_unity)

VOTES_FILE = "assets/data/federal-member-votes.json"
MEMBERS_FILE = "assets/data/current-members.json"
OUT_FILE = "assets/data/federal-party-unity.json"

#: Below this many members in a cohort, a rank says nothing worth printing:
#: Georgia has two senators, and "2nd of 2" is noise where a direct comparison
#: against the other senator is informative. The page mirrors this constant and
#: switches to a peer comparison below it. Ranks are emitted either way - the
#: decision about what to SHOW belongs to the page, not to the data.
RANK_MIN_COHORT = 5

#: Scores are published to four decimal places, matching generate_party_unity.py.
PRECISION = 4


def member_chamber(member):
    """'House'/'Senate' from the member's most recent term, or None.

    Terms run oldest -> newest, so a House member who moved to the Senate is read
    from item[-1]. Matches the convention in CLAUDE.md and congress.js.
    """
    terms = (member.get("terms") or {}).get("item") or []
    if not isinstance(terms, list):
        terms = [terms]
    if not terms:
        return None
    chamber = (terms[-1] or {}).get("chamber") or ""
    if "House" in chamber:
        return "House"
    if "Senate" in chamber:
        return "Senate"
    return None


def competition_ranks(scored):
    """`{key: rank}` by descending value, standard competition ranking.

    Ties share the lower rank and the next rank skips by the size of the tie, so
    two members tied at 2 are followed by 4. A rank implies an ordering, and
    equal scores are not an ordering.
    """
    ordered = sorted(scored.items(), key=lambda kv: -kv[1])
    ranks = {}
    previous_value = None
    previous_rank = 0
    for position, (key, value) in enumerate(ordered, start=1):
        if previous_value is not None and value == previous_value:
            ranks[key] = previous_rank
        else:
            ranks[key] = position
            previous_rank = position
            previous_value = value
    return ranks


def median(values):
    """Median of a list, or None when it is empty."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2, PRECISION)


def build_scorecard(votes_data, members_data):
    """The complete output document, from already-loaded inputs.

    Kept separate from file IO so the invariants can be tested against a built
    fixture rather than the committed data, whose shape changes weekly.
    """
    votes = votes_data.get("votes") or {}
    member_votes = votes_data.get("memberVotes") or {}

    roster = {}
    for m in (members_data.get("members") or []):
        bioguide = m.get("bioguideId")
        if not bioguide or m.get("state") != "Georgia":
            continue
        chamber = member_chamber(m)
        if chamber:
            roster[bioguide] = (chamber, m.get("partyName"), m.get("name"))

    # A member with roll calls but no roster entry has left mid-Congress. We have
    # no party for them, so no unity score is possible - and a scorecard that
    # quietly scored them as 0% would be publishing a falsehood about a real
    # person. They are excluded and counted instead.
    not_in_roster = sorted(set(member_votes) - set(roster))

    scores = {}
    for bioguide, (chamber, party, name) in roster.items():
        entries = member_votes.get(bioguide) or []

        # Own chamber only. A member votes in one chamber; anything else in their
        # record is a data fault and must not reach the denominator.
        own = {}
        for entry in entries:
            vote_id = entry.get("voteId")
            meta = votes.get(vote_id)
            if not meta or meta.get("chamber") != chamber:
                continue
            own.setdefault(vote_id, entry.get("vote"))

        # Anything recorded that is not an absence counts as a vote cast -- a
        # Speaker election records the candidate's NAME, and that is a ballot,
        # not a no-show. See ABSTENTIONS.
        total, cast, missed = score_participation(own, abstentions=ABSTENTIONS)

        tallies = {vote_id: (votes.get(vote_id) or {}).get("partyTally") for vote_id in own}
        party_line, aligned = score_unity(own, tallies, party)

        # A sitting member whose chamber has not voted since they were sworn in has
        # an empty record, which is not the same as a bad one. They stay in the
        # scorecard with null figures: dropping them made the validator report a
        # missing member and fail the run, which aborts the commit step for the
        # whole federal vote update — the scorecard taking down the dataset it is
        # derived from. The roster refreshes daily and the votes weekly, so this
        # window opens every time someone is seated during a recess.
        unity = round(aligned / party_line, PRECISION) if party_line else None
        scores[bioguide] = {
            "name": name,
            "chamber": chamber,
            "party": party,
            "totalRollCalls": total,
            "cast": cast,
            "missed": missed,
            "participationRate": round(cast / total, PRECISION) if total else None,
            "missedRate": round(missed / total, PRECISION) if total else None,
            "partyUnity": unity,
            "partyLineVotes": party_line,
            "votedWithParty": aligned,
            # The complement of unity, and null for the same reason: "broke with
            # the party 0% of the time" is a claim we cannot make without any
            # party-line votes to measure.
            "independenceRate": round(1 - aligned / party_line, PRECISION) if party_line else None,
        }

    delegation = {}
    for chamber in ("House", "Senate"):
        cohort = {b: s for b, s in scores.items() if s["chamber"] == chamber}
        if not cohort:
            continue
        unity_ranks = competition_ranks(
            {b: s["partyUnity"] for b, s in cohort.items() if s["partyUnity"] is not None})
        participation_ranks = competition_ranks(
            {b: s["participationRate"] for b, s in cohort.items()
             if s["participationRate"] is not None})
        for bioguide, entry in cohort.items():
            entry["unityRank"] = unity_ranks.get(bioguide)
            entry["participationRank"] = participation_ranks.get(bioguide)
            entry["cohortSize"] = len(cohort)
        delegation[chamber] = {
            "cohortSize": len(cohort),
            "medianUnity": median([s["partyUnity"] for s in cohort.values()
                                   if s["partyUnity"] is not None]),
            "medianParticipation": median([s["participationRate"] for s in cohort.values()
                                           if s["participationRate"] is not None]),
        }

    votes_meta = votes_data.get("metadata") or {}
    return {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "congress": votes_meta.get("congress"),
            "sessionName": votes_meta.get("sessionName"),
            "source": "Derived from federal-member-votes.json "
                      "(Clerk of the House + Senate.gov roll calls)",
            "scope": "Georgia's congressional delegation, every recorded roll call "
                     "of the Congress",
            "rankMinCohort": RANK_MIN_COHORT,
            "methodology": {
                "partyUnity": "Share of party-line roll calls (own-party majority "
                              "opposite the other party's majority) on which the member "
                              "voted with their own caucus. Excludes lopsided and "
                              "bipartisan votes.",
                "participation": "Share of the roll calls held in the member's chamber "
                                 "while they were seated on which they cast a ballot of any "
                                 "kind, including a candidate name in a Speaker election; "
                                 "not voting, present, absent and excused count against it.",
            },
            "count": len(scores),
            "scoredForUnity": sum(1 for s in scores.values() if s["partyUnity"] is not None),
            "withVotesButNotInRoster": len(not_in_roster),
        },
        "members": scores,
        "delegation": delegation,
    }


def main():
    votes_path = sys.argv[1] if len(sys.argv) > 1 else VOTES_FILE
    members_path = sys.argv[2] if len(sys.argv) > 2 else MEMBERS_FILE
    out_path = sys.argv[3] if len(sys.argv) > 3 else OUT_FILE

    with open(votes_path, encoding="utf-8") as fh:
        votes_data = json.load(fh)
    with open(members_path, encoding="utf-8") as fh:
        members_data = json.load(fh)

    doc = build_scorecard(votes_data, members_data)
    write_json_atomic(out_path, doc, indent=2)

    meta = doc["metadata"]
    print(f"Wrote {out_path}: {meta['count']} members "
          f"({meta['scoredForUnity']} with a party-unity score, "
          f"{meta['withVotesButNotInRoster']} with votes but no roster entry)")


if __name__ == "__main__":
    main()
