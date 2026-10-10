#!/usr/bin/env python3
"""Tests for lib.ga_vote_rules and the two generators' derive_result wrappers.

Guards the rule a roll-call "result" follows: simple majority, except a resolution
proposing a Georgia constitutional amendment, which needs two-thirds of the chamber's
elected members (House 120 / Senate 38). Before this, HR 1114 (House 99-73) and the
Senate's lost amendments (SR 838 at 32-23, SR 875 at 28-21, SR 668 at 29-21) were
published as "Pass" on a bare majority.

Usage:
  python scripts/test_ga_vote_rules.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ga_vote_rules import is_state_constitutional_amendment, vote_passed  # noqa: E402
from generate_ga_votes_soap import derive_result as votes_result  # noqa: E402
from generate_ga_bills_soap import derive_result as bills_result  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


# --- simple majority is unchanged for ordinary votes -------------------------
check("bill majority", vote_passed(90, 80, "lower"), True)
check("bill tie fails", vote_passed(80, 80, "lower"), False)
check("bill minority", vote_passed(60, 100, "upper"), False)
check("absent tally", vote_passed(None, 5, "lower"), None)

# --- constitutional amendments need 2/3 of the ELECTED members ---------------
check("CA house 99-73 fails", vote_passed(99, 73, "lower", True), False)      # HR 1114
check("CA house 119 fails", vote_passed(119, 0, "lower", True), False)
check("CA house 120 passes", vote_passed(120, 60, "lower", True), True)
check("CA house 162-0 passes", vote_passed(162, 0, "House", True), True)       # HR 1243
check("CA senate 32-23 fails", vote_passed(32, 23, "upper", True), False)      # SR 838
check("CA senate 28-21 fails", vote_passed(28, 21, "Senate", True), False)     # SR 875
check("CA senate 37 fails", vote_passed(37, 0, "upper", True), False)
check("CA senate 38 passes", vote_passed(38, 18, "upper", True), True)
check("CA senate 49-0 passes", vote_passed(49, 0, "upper", True), True)        # HR 1243 re-vote
# Unknown chamber must not invent a threshold.
check("CA unknown chamber falls back", vote_passed(60, 50, None, True), True)

# --- detection: Georgia amendment vs US Constitution --------------------------
check("state amendment",
      is_state_constitutional_amendment(
          "A RESOLUTION proposing an amendment to the Constitution so as to authorize the General Assembly"), True)
check("state amendment w/ CA tag",
      is_state_constitutional_amendment("CA A RESOLUTION proposing an amendment to the Constitution of Georgia"), True)
check("US amendment excluded",
      is_state_constitutional_amendment(
          "A RESOLUTION proposing an amendment to the Constitution of the United States"), False)
check("US convention call excluded",
      is_state_constitutional_amendment("A RESOLUTION to call a convention under Article V"), False)
check("study committee", is_state_constitutional_amendment(
    "A RESOLUTION creating the Senate Addressing Felony Disenfranchisement in Georgia's Constitution Study Committee"), False)
check("empty", is_state_constitutional_amendment(None), False)

# --- both generators agree, in their own casing -------------------------------
for yea, nay, chamber, ca in [(99, 73, "lower", True), (49, 0, "upper", True),
                              (100, 50, "lower", False), (10, 20, "upper", False)]:
    v = votes_result(yea, nay, "House" if chamber == "lower" else "Senate", ca)
    b = bills_result(yea, nay, chamber, ca)
    check("generators agree %s-%s" % (yea, nay), (v or "").lower(), b)
check("votes casing", votes_result(99, 73, "House", True), "Fail")
check("bills casing", bills_result(99, 73, "lower", True), "fail")
check("votes simple default", votes_result(5, 3), "Pass")

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
