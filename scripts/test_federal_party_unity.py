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
import json
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
        # H5 is the Speaker-election shape: no party tally, and the member's
        # "vote" is the candidate's name. They turned up and voted.
        "OLD00001": ([{"voteId": v, "vote": "Yea"} for v in ("H1", "H2", "H3", "H4", "S1")]
                     + [{"voteId": "H5", "vote": "Johnson (LA)"}]),
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
    # Sworn in during a recess: on the roster, but their chamber has not held a
    # roll call since. current-members.json refreshes daily and the vote record
    # weekly, so this window is real and recurring.
    member("NOVOTE01", HOUSE, R),
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
# A Speaker election records the candidate's name as the vote. Counting that as a
# missed vote publishes a member as having skipped a roll call they turned up for.
check("a named ballot counts as a vote cast, not a missed one",
      (m["OLD00001"]["cast"], m["OLD00001"]["missed"]), (5, 0))

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

# A sitting member with no roll calls yet must still appear. Dropping them made the
# validator report a missing member and exit 1, which aborts the commit step for the
# WHOLE federal vote update — the scorecard taking down the dataset it derives from.
print("a sitting member whose chamber has not voted since they arrived:")
check("is present rather than dropped", "NOVOTE01" in m, True)
check("has an empty record, not a zero score",
      (m["NOVOTE01"]["totalRollCalls"], m["NOVOTE01"]["participationRate"],
       m["NOVOTE01"]["partyUnity"]), (0, None, None))
check("is not ranked", m["NOVOTE01"]["unityRank"], None)
# That they do not fail the validator is asserted in its own section below, where
# `problems` is in scope.

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
check("cohort is the chamber delegation, including the member with no votes yet",
      m["OLD00001"]["cohortSize"], 7)

print("the delegation block:")
check("the chamber median ignores unscored members",
      doc["delegation"]["House"]["medianUnity"], 0.5)
check("the senate cohort is reported even when below the rank threshold",
      doc["delegation"]["Senate"]["cohortSize"], 1)
check("the rank threshold is published so the page can mirror it",
      RANK_MIN_COHORT, 5)

# ---------------------------------------------------------------------------
# The structural validator (validate_federal_party_unity.py). Counts cannot see
# shape: an artifact whose rates had drifted above 1, or that had quietly lost a
# member, is still valid JSON of about the right size.
#
# RULING (plan defect): the brief gave this `problems(scorecard, votes)`, but one
# of the checks the spec asks for -- that every sitting Georgia roster member is
# present -- cannot be made without the roster. The signature takes it as a third
# argument and the CLI a third path.

from validate_federal_party_unity import problems  # noqa: E402


def mutated(**member_fields):
    """A copy of the good document with OLD00001's fields overridden."""
    copy = json.loads(json.dumps(doc))
    copy["members"]["OLD00001"].update(member_fields)
    return copy


print("the structural validator:")
check("a clean document has no problems", problems(doc, VOTES, MEMBERS), [])
# The clean document above already contains NOVOTE01, so this doubles as the proof
# that a sitting member with an empty record does not fail the build.
check("a member with no roll calls yet is tolerated",
      [p for p in problems(doc, VOTES, MEMBERS) if "NOVOTE01" in p], [])
check("a rate above 1 is caught",
      len(problems(mutated(participationRate=1.5), VOTES, MEMBERS)), 1)
check("votedWithParty above partyLineVotes is caught",
      len(problems(mutated(votedWithParty=99), VOTES, MEMBERS)), 1)
check("cast above totalRollCalls is caught",
      len(problems(mutated(cast=99), VOTES, MEMBERS)), 1)
check("more roll calls than the chamber held is caught",
      len(problems(mutated(totalRollCalls=99), VOTES, MEMBERS)), 1)

dropped = json.loads(json.dumps(doc))
del dropped["members"]["OLD00001"]
check("a sitting roster member missing from the scorecard is caught",
      len(problems(dropped, VOTES, MEMBERS)), 1)

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    raise SystemExit(1)
print("All federal party-unity invariants hold.")
