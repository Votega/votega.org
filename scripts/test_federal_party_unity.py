#!/usr/bin/env python3
"""Invariants of the federal party-unity scorecard (generate_federal_party_unity.py).

The figures this produces are published claims about named legislators, so the
tests pin the claims rather than the plumbing: what goes in the denominator, what
is excluded from it, and — most importantly — what the generator says when it does
NOT know, since the failure mode that matters is publishing a confident zero.

The fixture is hand-built rather than sampled from the committed data: every
exclusion has to be exercised, and the real record's shape changes weekly.

Run: python scripts/test_federal_party_unity.py        (no network, no writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_federal_party_unity import RANK_MIN_COHORT, build_scorecard

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s: got %r, want %r" % (name, got, want))
        failures.append(name)


D, R = "Democratic", "Republican"


def tally(d_yea, d_nay, r_yea, r_nay):
    return {D: {"yea": d_yea, "nay": d_nay, "other": 0},
            R: {"yea": r_yea, "nay": r_nay, "other": 0}}


#: Five House roll calls: three party-line, one bipartisan, one with no tally at
#: all (the shape the Speaker election takes in the real data). Plus two Senate
#: roll calls the House members must never be scored against.
VOTES = {
    "metadata": {"congress": 119, "sessionName": "119th Congress"},
    "votes": {
        "H1": {"chamber": "House",  "partyTally": tally(0, 5, 5, 0)},
        "H2": {"chamber": "House",  "partyTally": tally(0, 5, 5, 0)},
        "H3": {"chamber": "House",  "partyTally": tally(0, 5, 5, 0)},
        "H4": {"chamber": "House",  "partyTally": tally(5, 0, 5, 0)},   # bipartisan
        "H5": {"chamber": "House",  "partyTally": None},                 # no tally
        "S1": {"chamber": "Senate", "partyTally": tally(5, 0, 0, 5)},
        "S2": {"chamber": "Senate", "partyTally": tally(5, 0, 0, 5)},
    },
    "memberVotes": {
        # Full-term member. The S1 entry is deliberate: a House member must never
        # be scored against a Senate roll call even if one reaches their record.
        "OLD00001": [{"voteId": v, "vote": "Yea"} for v in ("H1", "H2", "H3", "H4", "H5", "S1")],
        # Arrived mid-Congress: present for two roll calls, neither party-line.
        "NEW00001": [{"voteId": "H4", "vote": "Yea"}, {"voteId": "H5", "vote": "Yea"}],
        "NOPL0001": [{"voteId": "H4", "vote": "Yea"}, {"voteId": "H5", "vote": "Nay"}],
        "TIED0001": [{"voteId": "H1", "vote": "Yea"}, {"voteId": "H2", "vote": "Nay"}],
        "TIED0002": [{"voteId": "H1", "vote": "Yea"}, {"voteId": "H2", "vote": "Nay"}],
        "LAST0001": [{"voteId": "H1", "vote": "Nay"}, {"voteId": "H2", "vote": "Nay"}],
        "SEN00001": [{"voteId": "S1", "vote": "Yea"}, {"voteId": "S2", "vote": "Yea"}],
        # Departed mid-Congress: the roll calls remember them, the roster does not.
        "GHOST001": [{"voteId": "H1", "vote": "Yea"}],
    },
}


def member(bioguide, chamber, party):
    return {"bioguideId": bioguide, "state": "Georgia", "partyName": party,
            "terms": {"item": [{"chamber": chamber}]}}


HOUSE = "House of Representatives"
MEMBERS = {"members": [
    member("OLD00001", HOUSE, R),
    member("NEW00001", HOUSE, R),
    member("NOPL0001", HOUSE, D),
    member("TIED0001", HOUSE, R),
    member("TIED0002", HOUSE, R),
    member("LAST0001", HOUSE, R),
    member("SEN00001", "Senate", D),
    # Another state's member, with no votes here: must not reach the scorecard.
    {"bioguideId": "OTHER001", "state": "Ohio", "partyName": R,
     "terms": {"item": [{"chamber": HOUSE}]}},
]}

doc = build_scorecard(VOTES, MEMBERS)
m = doc["members"]

print("the denominator is the member's own seated window:")
check("a mid-Congress arrival is scored against their own window",
      m["NEW00001"]["totalRollCalls"], 2)
check("the full-term member is scored against all of them",
      m["OLD00001"]["totalRollCalls"], 5)
check("the other chamber's roll calls are excluded",
      m["SEN00001"]["totalRollCalls"], 2)

print("what is excluded from the unity denominator:")
# H1-H3 are party-line; H4 is bipartisan; H5 has no tally. Only the three count.
check("a bipartisan roll call and one with no party tally are both skipped",
      m["OLD00001"]["partyLineVotes"], 3)
check("unity is null, never zero, with no party-line votes",
      (m["NOPL0001"]["partyUnity"], m["NOPL0001"]["partyLineVotes"]), (None, 0))
check("independence is null too when unity is", m["NOPL0001"]["independenceRate"], None)

print("members the scorecard cannot speak for:")
check("a member with votes but no roster entry is excluded",
      "GHOST001" in m, False)
check("...and is counted in metadata", doc["metadata"]["withVotesButNotInRoster"], 1)
check("another state's member is not scored", "OTHER001" in m, False)

print("ranking:")
check("rank 1 is the top of the metric", m["OLD00001"]["unityRank"], 1)
# OLD scores 1.0, the two TIED members 0.5 each, LAST 0.0. Standard competition
# ranking: the tie shares rank 2 and the next rank skips to 4.
#
# RULING (plan defect): the plan asserted [1, 1, 3] here while also asserting
# OLD00001 is rank 1. Three members cannot share rank 1 and leave LAST at 3. The
# fixture gives OLD a unique top score, so the tie lands at 2 and the skip at 4,
# which preserves both things the plan meant to pin.
check("ties share a rank and the next rank skips",
      [m[b]["unityRank"] for b in ("TIED0001", "TIED0002", "LAST0001")], [2, 2, 4])
check("a member with no unity score is not ranked", m["NOPL0001"]["unityRank"], None)
check("cohort is the chamber delegation", m["OLD00001"]["cohortSize"], 6)

print("the delegation block:")
check("the chamber median ignores unscored members",
      doc["delegation"]["House"]["medianUnity"], 0.5)
check("the senate cohort is reported even when below the rank threshold",
      doc["delegation"]["Senate"]["cohortSize"], 1)
check("the rank threshold is published so the page can mirror it",
      RANK_MIN_COHORT, 5)

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    raise SystemExit(1)
print("All federal party-unity invariants hold.")
