#!/usr/bin/env python3
"""The CQ party-line rule, pinned clause by clause (lib/party_unity.py).

"Party unity" is only meaningful if "party-line vote" means one thing. It used to
mean one thing in scripts/generate_party_unity.py and another, hand-maintained copy
of the same thing in ga-member.html's client JS; the federal scorecard would have
been a third. These tests pin the shared rule so the copies can't drift apart
without something going red.

Each exclusion clause gets its own case, because each one is a different claim
about what the data means, and each one fires in the real record: of the 1,591
roll calls in the 119th Congress, 3 have a tied caucus, 275 have both caucuses
voting the same way, and 1 (the Speaker election, whose "votes" are candidate
names) has no party tally at all.

Run: python scripts/test_party_unity_rule.py        (no network, no writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.party_unity import (ABSTENTIONS, OTHER_PARTY, party_line_direction,
                             score_participation,
                             score_unity)

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s: got %r, want %r" % (name, got, want))
        failures.append(name)


D, R = "Democratic", "Republican"
PL = {D: {"yea": 0, "nay": 10}, R: {"yea": 9, "nay": 1}}   # party-line, R majority Yea

print("the two caucuses point in opposite directions:")
check("party-line gives own-caucus direction", party_line_direction(PL, R, D), "Yea")
check("same roll call from the other side", party_line_direction(PL, D, R), "Nay")

print("a roll call that is not a party-line vote:")
check("no tally is not a party-line vote", party_line_direction(None, R, D), None)
check("empty tally is not a party-line vote", party_line_direction({}, R, D), None)
check("tied own caucus excluded",
      party_line_direction({D: {"yea": 5, "nay": 5}, R: {"yea": 9, "nay": 1}}, D, R), None)
check("tied other caucus excluded",
      party_line_direction({D: {"yea": 5, "nay": 5}, R: {"yea": 9, "nay": 1}}, R, D), None)
check("both caucuses agree excluded",
      party_line_direction({D: {"yea": 8, "nay": 1}, R: {"yea": 9, "nay": 1}}, R, D), None)
check("lone own-party voter excluded",
      party_line_direction({D: {"yea": 1, "nay": 0}, R: {"yea": 9, "nay": 1}}, D, R), None)
check("silent other caucus excluded",
      party_line_direction({D: {"yea": 0, "nay": 0}, R: {"yea": 9, "nay": 1}}, R, D), None)

VOTES = {"a": "Yea", "b": "Nay", "c": "Not Voting", "d": "Yea"}
TALLIES = {"a": PL, "b": PL, "c": PL, "d": {D: {"yea": 8, "nay": 1}, R: {"yea": 9, "nay": 1}}}

print("scoring a member's record:")
check("unity counts only party-line votes the member cast", score_unity(VOTES, TALLIES, R), (2, 1))
check("an absence is not a defection", score_unity({"c": "Not Voting"}, TALLIES, R), (0, 0))
check("participation counts Yea and Nay only", score_participation(VOTES), (4, 3, 1))
check("participation of an empty record", score_participation({}), (0, 0, 0))

# A Speaker election records the candidate's NAME as each member's vote. That is a
# ballot cast, not an absence — counting it as missed publishes a member as having
# skipped a vote they turned up for. The GA record has no such value, so the GA
# rule (cast == Yea or Nay) stays the default and the federal generator opts in.
print("a recorded ballot that is neither Yea, Nay, nor an absence:")
SPEAKER = {"a": "Yea", "b": "Johnson (LA)", "c": "Not Voting"}
check("by default a named ballot does not count as cast (the GA rule)",
      score_participation(SPEAKER), (3, 1, 2))
check("with an abstention list, a named ballot counts as cast",
      score_participation(SPEAKER, abstentions=ABSTENTIONS), (3, 2, 1))
check("an absence still counts against participation",
      score_participation({"c": "Not Voting"}, abstentions=ABSTENTIONS), (1, 0, 1))
check("every absence vocabulary value is treated the same",
      score_participation({v: v for v in ABSTENTIONS}, abstentions=ABSTENTIONS),
      (len(ABSTENTIONS), 0, len(ABSTENTIONS)))

print("the caucus map:")
check("the two major caucuses oppose each other",
      (OTHER_PARTY.get(D), OTHER_PARTY.get(R)), (R, D))
check("a third party has no defined opposite", OTHER_PARTY.get("Independent"), None)

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    raise SystemExit(1)
print("All party-line rule invariants hold.")
