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


# latest.json keeps pointing at earlier General Assemblies after a rollover.
import tempfile  # noqa: E402

def frozen(root, tag, biennium, sessions, frozen_flag=True):
    os.makedirs(os.path.join(root, tag), exist_ok=True)
    meta = {"biennium": biennium, "frozenAt": "2027-01-11T00:00:00+00:00",
            "totalBills": sum(c for _, c in sessions),
            "sessions": [{"id": i, "name": i, "billCount": c} for i, c in sessions]}
    if frozen_flag:
        meta.update(frozen=True, frozenTag=tag)
    with open(os.path.join(root, tag, "ga-bills.json"), "w", encoding="utf-8") as fh:
        json.dump({"metadata": meta, "bills": []}, fh)

with tempfile.TemporaryDirectory() as root:
    pattern = os.path.join(root, "*", "ga-bills.json")
    check("no frozen file: nothing earlier", P.earlier_bienniums(pattern, "2027-2028"), [])
    frozen(root, "2025_26", "2025-2026", [("2025_26", 5480), ("2026_ss", 176)])
    check("a freeze of the CURRENT biennium is not earlier (frozen before the bump)",
          P.earlier_bienniums(pattern, "2025-2026"), [])
    got = P.earlier_bienniums(pattern, "2027-2028")
    check("after the bump the frozen biennium is listed", [b["biennium"] for b in got], ["2025-2026"])
    check("its sessions point at the folders already published",
          [(s["slug"], s["billCount"], s["files"]["bills"]) for s in got[0]["sessions"]],
          [("2025-2026", 5480, "sessions/2025-2026/bills.json"),
           ("2026-ss", 176, "sessions/2026-ss/bills.json")])
    check("same file layout as a current session", sorted(got[0]["sessions"][0]["files"]),
          ["bills", "billsCsv", "schema", "subjects", "summary"])
    frozen(root, "2023_24", "2023-2024", [("2023_24", 4000)])
    check("newest first", [b["biennium"] for b in P.earlier_bienniums(pattern, "2027-2028")],
          ["2025-2026", "2023-2024"])
    frozen(root, "2021_22", "2021-2022", [("2021_22", 1)], frozen_flag=False)
    try:
        P.earlier_bienniums(pattern, "2027-2028"); refused = False
    except SystemExit:
        refused = True
    check("a file not marked frozen refuses the publish", refused, True)

arts = P.build_artifacts()
latest = json.loads(arts["latest.json"])
check("today latest.json lists no earlier biennium (the freeze is the current one)",
      latest["earlierBienniums"], [])
check("current-session fields unchanged", sorted(k for k in latest if k != "earlierBienniums"),
      ["activeSession", "biennium", "billCount", "currentSession", "generatedAt", "sessions"])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll checks passed.")
