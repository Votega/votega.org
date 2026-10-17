#!/usr/bin/env python3
"""Assert validate_unopposed_seats.py gates on self-contradiction and only reports change.

Usage:
  python scripts/test_unopposed_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_unopposed_seats as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def sound():
    """A self-consistent file at full strength, in the shape the generator emits."""
    seats = [
        {"id": "ga-house-7-2026", "chamber": "house", "district": 7,
         "party": "Republican", "candidate": "A"},
        {"id": "ga-house-9-2026", "chamber": "house", "district": 9,
         "party": "Democrat", "candidate": "B"},
        {"id": "ga-senate-3-2026", "chamber": "senate", "district": 3,
         "party": None, "candidate": None},
    ]
    return {
        "metadata": {"cycle": 2026}, "cycle": 2026,
        "total": 236, "unopposed": 3, "contested": 233,
        "unopposedPct": round(3 / 236 * 100, 1),
        "republicanSafe": 1, "democraticSafe": 1,
        "byChamber": {
            "house": {"total": 180, "unopposed": 2, "republicanSafe": 1, "democraticSafe": 1},
            "senate": {"total": 56, "unopposed": 1, "republicanSafe": 0, "democraticSafe": 0},
        },
        "seats": seats,
    }


def has(errs, text):
    return any(text in e for e in errs)


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound(); d["total"] = 237
    check("chamber totals not summing is tier 1", has(V.tier1(d), "do not sum"), True)

    d = sound(); d["unopposed"] = 4; d["contested"] = 232
    check("chamber unopposed not summing is tier 1", has(V.tier1(d), "do not sum"), True)

    d = sound(); d["contested"] = 200
    check("unopposed + contested != total is tier 1", has(V.tier1(d), "!= total"), True)

    d = sound(); d["seats"].pop()
    check("a seat list shorter than the count is tier 1", has(V.tier1(d), "seat list length"), True)

    d = sound(); d["seats"][1]["id"] = d["seats"][0]["id"]
    check("a seat listed twice is tier 1", has(V.tier1(d), "more than once"), True)

    d = sound(); d["seats"][0]["chamber"] = "senate"
    check("seats disagreeing with byChamber is tier 1", has(V.tier1(d), "seats listed but"), True)

    d = sound()
    d["byChamber"]["senate"]["total"] = 57; d["total"] = 237; d["contested"] = 234
    check("a chamber above its constitutional size is tier 1",
          has(V.tier1(d), "the chamber has 56"), True)

    d = sound(); d["unopposedPct"] = 99.0
    check("a percentage that is not unopposed/total is tier 1",
          has(V.tier1(d), "unopposedPct"), True)

    d = sound(); del d["byChamber"]["house"]
    check("a missing chamber is tier 1", V.tier1(d) != [], True)

    # The world moving must NOT gate. The old window was 150 <= total <= 260.
    d = sound()
    d["byChamber"]["house"]["total"] = 100; d["total"] = 156; d["contested"] = 153
    d["unopposedPct"] = round(3 / 156 * 100, 1)
    check("races.json missing 80 House seats is NOT tier 1", V.tier1(d), [])

    d = sound()
    d["byChamber"]["house"].update(total=0, unopposed=0, republicanSafe=0, democraticSafe=0)
    d["byChamber"]["senate"].update(total=0, unopposed=0)
    d.update(total=0, unopposed=0, contested=0, unopposedPct=0, republicanSafe=0,
             democraticSafe=0, seats=[])
    check("an empty-but-consistent file is NOT tier 1", V.tier1(d), [])


def tier2_cases():
    short_head = "A chamber is below full strength in races.json"
    contested_head = "Seats that are now contested (or left races.json)"
    old = sound()
    check("no change, full strength -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline, full strength -> nothing to report", V.tier2(sound(), None), [])

    d = sound(); d["byChamber"]["house"]["total"] = 178
    secs = dict(V.tier2(d, None))
    check("a short chamber is reported without a baseline", short_head in secs, True)
    check("and the report says which chamber and by how many",
          "2 missing" in secs[short_head][0] and "House" in secs[short_head][0], True)

    new = copy.deepcopy(old)
    new["seats"].pop(0); new["unopposed"] = 2; new["contested"] = 234
    new["byChamber"]["house"]["unopposed"] = 1
    secs = dict(V.tier2(new, old))
    check("a seat turning contested is reported", contested_head in secs, True)
    check("and is named", "House district 7" in secs[contested_head][0], True)
    check("headline numbers are reported", "Headline numbers" in secs, True)

    new = copy.deepcopy(old)
    new["seats"].append({"id": "ga-senate-9-2026", "chamber": "senate", "district": 9,
                         "party": "Republican", "candidate": "C"})
    check("a newly unopposed seat is reported",
          "Seats that became unopposed" in dict(V.tier2(new, old)), True)


if __name__ == "__main__":
    print("tier 1:")
    tier1_cases()
    print("tier 2:")
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
