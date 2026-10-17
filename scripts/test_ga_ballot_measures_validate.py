#!/usr/bin/env python3
"""Assert validate_ga_ballot_measures.py catches each contradiction the old heredoc did.

Usage:
  python scripts/test_ga_ballot_measures_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_ga_ballot_measures as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


# The real schema, so the enums come from the one place production reads them.
SCHEMA = json.load(open(os.path.join(HERE, "..", V.SCHEMA), encoding="utf-8"))


def sound():
    return {"metadata": {}, "measures": [
        {"id": "ga-2026-a", "status": "certified", "type": "Constitutional Amendment",
         "title": "A", "summary": "s"},
        {"id": "ga-2024-b", "status": "passed", "type": "Statewide Referendum",
         "title": "B", "summary": "s", "results": {"yes": 1, "no": 0}},
    ]}


def has(errs, text):
    return any(text in e for e in errs)


check("the real committed file is clean",
      V.tier1(json.load(open(os.path.join(HERE, "..", V.SRC), encoding="utf-8")), SCHEMA), [])
check("a sound doc raises nothing", V.tier1(sound(), SCHEMA), [])

d = sound(); d["measures"] = []
check("no measures is an error", has(V.tier1(d, SCHEMA), "no measures"), True)

d = sound(); del d["measures"][0]["title"]
check("a missing required field is an error", has(V.tier1(d, SCHEMA), "missing required field 'title'"), True)

d = sound(); d["measures"][0]["status"] = "pending"
check("a status outside the schema enum is an error", has(V.tier1(d, SCHEMA), "invalid status"), True)

d = sound(); d["measures"][0]["type"] = "Ballot Question"
check("a type outside the schema enum is an error", has(V.tier1(d, SCHEMA), "invalid type"), True)

d = sound(); d["measures"][1]["id"] = "ga-2026-a"
check("a duplicate id is an error", has(V.tier1(d, SCHEMA), "duplicate"), True)

d = sound(); d["measures"][0]["id"] = "GA 2026 A"
check("an id that is not a slug is an error", has(V.tier1(d, SCHEMA), "schema pattern"), True)

d = sound(); d["measures"][0]["bogus"] = 1
check("a key the schema does not declare is an error", has(V.tier1(d, SCHEMA), "does not declare"), True)

d = sound(); del d["measures"][1]["results"]
check("a terminal status without results is an error", has(V.tier1(d, SCHEMA), "no results object"), True)

d = sound(); d["measures"][0]["results"] = {"yes": 1}
check("results on a non-terminal status is an error", has(V.tier1(d, SCHEMA), "has results but status"), True)

# The vocabulary comes from the schema: widening the schema widens the check.
wide = copy.deepcopy(SCHEMA)
wide["$defs"]["measure"]["properties"]["type"]["enum"].append("Ballot Question")
d = sound(); d["measures"][0]["type"] = "Ballot Question"
check("a type added to the schema is accepted (no second copy to edit)",
      V.tier1(d, wide), [])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll checks passed.")
