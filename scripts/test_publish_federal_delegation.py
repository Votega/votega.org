#!/usr/bin/env python3
"""Assert publish_federal_delegation.check_sources refuses only for real contradictions.

Usage:
  python scripts/test_publish_federal_delegation.py

Exits 0 on success, 1 on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_federal_delegation as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def refuses(ga, doc):
    try:
        P.check_sources(ga, doc)
    except SystemExit as e:
        return str(e)
    return None


GA = [{"bioguideId": "W000790"}]
VOTES = {"votes": {"H2026_0001": {}}, "memberVotes": {"W000790": [{"voteId": "H2026_0001", "vote": "Yea"}]}}

check("a normal Congress publishes with no warning", P.check_sources(GA, VOTES), [])
check("no Georgia members is fatal", bool(refuses([], VOTES)), True)
check("votes with no memberVotes is fatal", bool(refuses(GA, {"votes": {"a": {}}, "memberVotes": {}})), True)
check("memberVotes with no votes is fatal", bool(refuses(GA, {"votes": {}, "memberVotes": {"x": []}})), True)

# The new-Congress window: the old gate held the whole publish, roster included.
warns = P.check_sources(GA, {"votes": {}, "memberVotes": {}})
check("a Congress with no roll calls yet is NOT fatal", len(warns), 1)
check("an absent votes section is treated as no roll calls", len(P.check_sources(GA, {})), 1)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll checks passed.")
