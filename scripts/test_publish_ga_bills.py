#!/usr/bin/env python3
"""Assert publish_ga_bills.gate_source refuses contradictions and only contradictions.

Usage:
  python scripts/test_publish_ga_bills.py

Exits 0 on success, 1 on any failure.
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_ga_bills as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def refuses(doc):
    try:
        P.gate_source(doc)
    except SystemExit:
        return True
    return False


# The real committed file is the one fixture guaranteed to match production's shape.
real = json.load(open(os.path.join(HERE, "..", P.SRC_JSON), encoding="utf-8"))
check("the committed file passes the gate", refuses(real), False)

d = copy.deepcopy(real); d["metadata"]["totalBills"] += 1
check("a wrong metadata.totalBills is refused (the old check missed it)", refuses(d), True)

d = copy.deepcopy(real); d["bills"].append(copy.deepcopy(d["bills"][0])); d["metadata"]["totalBills"] += 1
check("a duplicate bill is refused (the old check missed it)", refuses(d), True)

d = copy.deepcopy(real); d["metadata"]["sessions"][0]["billCount"] += 1
check("a per-session billCount that disagrees with its bills is refused", refuses(d), True)

check("a file with no bills is refused", refuses({"metadata": {}, "bills": []}), True)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll checks passed.")
