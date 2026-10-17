#!/usr/bin/env python3
"""Assert validate_general_placeholder.py gates on self-contradiction and only reports change.

Usage:
  python scripts/test_general_placeholder_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_general_placeholder as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def cand(name):
    return {"name": name, "votes": 0, "incumbent": False}


def race(office, *names):
    return {"office": office,
            "contests": [{"party": "rep", "totalVotes": 0, "candidates": [cand(n) for n in names]}]}


def sound():
    return [
        {"id": "statewide", "label": "S", "races": [race("Governor", "A"), race("US Senate", "B")]},
        {"id": "us-house", "label": "H", "races": [race("District 1", "C")]},
        {"id": "state-senate", "label": "SS", "races": [race("District 2", "D")]},
        {"id": "state-house", "label": "SH", "races": [race("District 3", "E")]},
        {"id": "courts", "label": "C", "races": [race("Supreme Court of Georgia (Seat 1)", "F")]},
    ]


def has(errs, text):
    return any(text in e for e in errs)


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound(); d[0]["races"][0]["contests"][0]["candidates"][0]["votes"] = 5
    d[0]["races"][0]["contests"][0]["totalVotes"] = 5
    check("a placeholder carrying votes is tier 1", has(V.tier1(d), "carries 5 votes"), True)

    d = sound(); d[0]["races"][0]["contests"][0]["totalVotes"] = 9
    check("totalVotes disagreeing with its candidates is tier 1", has(V.tier1(d), "totalVotes"), True)

    d = sound(); d[0]["races"][0]["contests"][0]["candidates"][0]["name"] = None
    check("a nameless candidate is tier 1", has(V.tier1(d), "no name"), True)

    d = sound(); d[1]["id"] = "statewide"
    check("a duplicate section id is tier 1", has(V.tier1(d), "more than once"), True)

    d = sound(); d[0]["races"].append(race("Governor", "Z"))
    check("a duplicate office is tier 1", has(V.tier1(d), "Governor"), True)

    check("a non-list top level is tier 1", V.tier1({"a": 1}) != [], True)

    # The world moving must NOT gate. The old heredoc required exactly 5 sections,
    # >= 300 offices and >= 400 candidates.
    d = sound(); d.pop()
    check("a missing section is NOT tier 1", V.tier1(d), [])
    d = sound(); d[3]["races"] = []
    check("an empty section is NOT tier 1", V.tier1(d), [])
    check("a tiny ballot (far under the old 300/400 floors) is NOT tier 1", V.tier1(sound()), [])
    check("an empty list of sections is NOT tier 1", V.tier1([]), [])


def tier2_cases():
    old = sound()
    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline, full shape -> nothing to report", V.tier2(sound(), None), [])

    d = sound(); d.pop()
    secs = dict(V.tier2(d, None))
    check("a missing section is reported and named",
          "`courts`" in "".join(secs.get("Sections differ from the expected five", [])), True)

    d = sound(); d[3]["races"] = []
    secs = dict(V.tier2(d, None))
    check("an empty section is reported and named",
          "`state-house`" in "".join(secs.get("Empty sections", [])), True)

    new = copy.deepcopy(old); new[2]["races"] = []
    secs = dict(V.tier2(new, old))
    check("offices vanishing from a section are reported with before/after",
          "1 offices / 1 candidates -> 0 / 0" in "".join(secs.get("Offices and candidates per section", [])), True)
    check("and the removed office is named",
          "state-senate/District 2" in "".join(secs.get("Offices removed from the ballot", [])), True)

    new = copy.deepcopy(old)
    new[0]["races"][0] = race("Governor", "A2")
    secs = dict(V.tier2(new, old))
    line = "".join(secs.get("Candidates changed on an existing ballot", []))
    check("a swapped candidate is reported by name", "off: A" in line and "on: A2" in line, True)

    new = copy.deepcopy(old); new[1]["races"].append(race("District 9", "G"))
    check("a new office is reported",
          "Offices added to the ballot" in dict(V.tier2(new, old)), True)

    new = copy.deepcopy(old)
    new[1]["races"] = [race(f"District {i}", f"N{i}") for i in range(60)]
    lines = dict(V.tier2(new, old))["Offices added to the ballot"]
    check("a large churn is capped", len(lines), V.MAX_LINES + 1)


if __name__ == "__main__":
    print("tier 1:")
    tier1_cases()
    print("tier 2:")
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
