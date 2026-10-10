#!/usr/bin/env python3
"""Tests for the roll-call join in enrich_bills_with_party_votes.

Guards two things: (1) two roll calls on one bill/day/tally (SB 76, 2026-04-02: PASSAGE
and "Agree to Senate Amend to House Sub", both 168-2) get distinct keys via the caption
instead of the last one silently winning; (2) calls that still collide are only resolved
when their rosters yield the same party tally.

Usage:
  python scripts/test_enrich_party_votes.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from enrich_bills_with_party_votes import _rollcall_key, resolve_vote_id  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


a = _rollcall_key("SB 76", "2026-04-02", 168, 2, "PASSAGE")
b = _rollcall_key("SB 76", "2026-04-02T10:00:00", 168, 2, "Agree to Senate Amend to House Sub")
check("captions separate the keys", a == b, False)
check("caption case/space insensitive",
      _rollcall_key("SB 76", "2026-04-02", 168, 2, " passage "), a)
check("bill spacing normalized", _rollcall_key("SB76", "2026-04-02", 168, 2, "PASSAGE"), a)
check("date trimmed to day", _rollcall_key("SB 76", "2026-04-02T23:59:59", 168, 2, "PASSAGE"), a)
check("missing caption tolerated", _rollcall_key("SB 76", "2026-04-02", 168, 2, None)[-1], "")

tallies = {"v1": {"R": 1}, "v2": {"R": 1}, "v3": {"R": 2}}
check("no candidates", resolve_vote_id([], tallies.get), None)
check("single candidate", resolve_vote_id(["v1"], tallies.get), "v1")
check("identical tallies resolve", resolve_vote_id(["v1", "v2"], tallies.get), "v1")
check("differing tallies refuse", resolve_vote_id(["v1", "v3"], tallies.get), None)
check("three-way partial disagreement refuses", resolve_vote_id(["v1", "v2", "v3"], tallies.get), None)

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
