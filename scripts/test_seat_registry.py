#!/usr/bin/env python3
"""Offline checks for the seat registry (docs/seat-history-design.md, Phase 1).

Pins: the block-identity rule (a district a new map left untouched keeps its seat; a
renumbered identical district is a new seat with an exact link), every tier-1 rule in
lib/seat_registry.registry_errors with a negative control, the stdlib xlsx reader, and
the committed artifacts (seats.json validates, matches a rebuild, and carries the
measured 2021 -> 2023 findings). Stdlib only, no network, no input files.

Usage: python scripts/test_seat_registry.py
"""
import copy
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.seat_registry import build_seats, compare_plans, registry_errors  # noqa: E402
from lib.xlsx_rows import read_rows  # noqa: E402
import build_seat_registry as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


# A three-district toy state. Old map: d1={a,b}, d2={c,d}, d3={e,f}.
# New map: d1 unchanged; old d2 and d3 swap numbers exactly (both renumbered identical).
# NEW_CHANGED instead mixes blocks, so nothing is identical.
OLD = {"a": 1, "b": 1, "c": 2, "d": 2, "e": 3, "f": 3}
NEW = {"a": 1, "b": 1, "e": 2, "f": 2, "c": 3, "d": 3}
NEW_CHANGED = {"a": 1, "b": 1, "c": 2, "e": 2, "d": 3, "f": 3}

PLANS = {
    "bodies": {"ga-house": {"districts": 3, "label": "Georgia House District"}},
    "plans": [
        {"id": "ga-house-2021", "body": "ga-house", "suffix": "2021", "effective": "2023-01-09",
         "supersededBy": "ga-house-2023"},
        {"id": "ga-house-2023", "body": "ga-house", "suffix": "2023", "effective": "2025-01-13",
         "supersededBy": None},
    ],
    "unmappedSeats": [{"id": "us-senate-ga-class-2", "body": "us-senate-ga",
                       "title": "U.S. Senate, Georgia (Class 2)", "facts": {"class": 2}}],
}
EXEC = [{"id": "ga-governor", "title": "Governor", "holders": []},
        {"id": "ga-lt-governor", "title": "Lieutenant Governor", "presidesOver": "Senate", "holders": []}]


def registry(comparison):
    seats = build_seats(PLANS, comparison, EXEC)
    return {"metadata": {"count": len(seats)}, "seats": seats}


def compare_cases():
    print("compare_plans (identity is the block set)")
    c = compare_plans(OLD, NEW)
    check("an untouched district is carried over", c["carriedOver"], [1])
    check("same number, different blocks is newly drawn", c["newlyDrawn"], [2, 3])
    check("identical blocks under a new number is found, both ways for a swap",
          c["renumberedIdentical"], [[3, 2], [2, 3]])
    c2 = compare_plans(OLD, NEW_CHANGED)
    check("no false renumbering when blocks only partly match", c2["renumberedIdentical"], [])
    try:
        compare_plans(OLD, {**NEW, "z": 1})
        got = "no error"
    except ValueError:
        got = "refused"
    check("plans over different blocks are refused", got, "refused")


def build_cases():
    print("build_seats")
    seats = {s["id"]: s for s in registry({"ga-house-2023": compare_plans(OLD, NEW)})["seats"]}
    check("the carried-over seat keeps its first map's id, with no @2023 twin",
          ("ga-house-1@2021" in seats, "ga-house-1@2023" in seats), (True, False))
    check("the carried-over seat is still in force", seats["ga-house-1@2021"]["redrawnBy"], None)
    check("a redrawn seat names the map that replaced it",
          seats["ga-house-2@2021"]["redrawnBy"], "ga-house-2023")
    check("the renumbered identical district gets an exact link to its new seat",
          seats["ga-house-3@2021"]["successorSeats"],
          [{"seatId": "ga-house-2@2023", "blockShare": 1.0, "populationShare": 1.0,
            "basis": "identical-blocks"}])
    check("statewide seats carry their facts and no map",
          (seats["ga-lt-governor"]["facts"], seats["ga-lt-governor"]["plan"]), ({"presidesOver": "Senate"}, None))
    check("US Senate seats are by class, with no map",
          (seats["us-senate-ga-class-2"]["facts"], seats["us-senate-ga-class-2"]["district"]), ({"class": 2}, None))


def validation_cases():
    print("registry_errors (tier 1), each with a negative control")
    cmp_ = {"ga-house-2023": compare_plans(OLD, NEW)}
    good = registry(cmp_)
    check("a correct registry passes", registry_errors(good, PLANS, cmp_, EXEC), [])
    check("and passes against itself as the previous copy",
          registry_errors(good, PLANS, cmp_, EXEC, previous=good), [])

    def broken(mutate):
        r = copy.deepcopy(good)
        mutate(r)
        return registry_errors(r, PLANS, cmp_, EXEC)

    check("duplicate seat id", any("duplicate" in e for e in broken(
        lambda r: r["seats"].append(copy.deepcopy(r["seats"][0])))), True)
    check("count mismatch", any("count" in e for e in broken(
        lambda r: r["metadata"].update(count=1))), True)
    check("a carried-over seat wrongly marked redrawn", any("carried it over" in e for e in broken(
        lambda r: next(s for s in r["seats"] if s["id"] == "ga-house-1@2021").update(redrawnBy="ga-house-2023"))), True)
    check("a district with no seat in force", any("in force" in e for e in broken(
        lambda r: next(s for s in r["seats"] if s["id"] == "ga-house-3@2023").update(redrawnBy="ga-house-2023"))), True)
    check("a seat id that doesn't match its map", any("does not match" in e for e in broken(
        lambda r: next(s for s in r["seats"] if s["id"] == "ga-house-1@2021").update(plan="ga-house-2023"))), True)
    check("a link to an unknown seat", any("unknown seat" in e for e in broken(
        lambda r: next(s for s in r["seats"] if s["id"] == "ga-house-3@2021")["successorSeats"][0].update(seatId="ga-house-9@2023"))), True)
    check("a map suffix on an unmapped seat", any("suffix" in e for e in broken(
        lambda r: next(s for s in r["seats"] if s["id"] == "ga-governor").update(id="ga-governor@2023"))), True)
    check("statewide seats drifting from ga-executive-seats.json",
          any("statewide" in e for e in registry_errors(good, PLANS, cmp_, EXEC[:1])), True)
    bad_cmp = {"ga-house-2023": {**cmp_["ga-house-2023"], "carriedOver": [1, 2]}}
    check("a comparison that doesn't partition the districts",
          any("partition" in e for e in registry_errors(good, PLANS, bad_cmp, EXEC)), True)
    bad_plans = copy.deepcopy(PLANS)
    bad_plans["plans"][0]["supersededBy"] = None
    check("a broken supersededBy chain", any("supersededBy" in e for e in
                                            registry_errors(good, bad_plans, cmp_, EXEC)), True)
    smaller = copy.deepcopy(good)
    smaller["seats"] = [s for s in smaller["seats"] if s["id"] != "ga-house-2@2021"]
    smaller["metadata"]["count"] = len(smaller["seats"])
    check("append-only: a published seat removed",
          any("removed" in e for e in registry_errors(smaller, PLANS, cmp_, EXEC, previous=good)), True)
    moved = copy.deepcopy(good)
    next(s for s in moved["seats"] if s["id"] == "ga-house-1@2021")["title"] = "renamed is fine"
    check("append-only: a title edit is allowed",
          registry_errors(moved, PLANS, cmp_, EXEC, previous=good), [])


def xlsx_cases():
    print("xlsx_rows (stdlib reader)")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.xlsx")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/sharedStrings.xml",
                       '<sst><si><t>Block</t></si><si><t>DistrictID:1</t></si>'
                       '<si><t>130010001001000</t></si><si><r><t>0</t></r><r><t>07</t></r></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData>'
                       '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>'
                       '<row r="3"><c r="A3" t="inlineStr"><is><t>130010001001001</t></is></c><c r="B3"><v>12</v></c></row>'
                       '<row r="4"><c r="B4"><v>5</v></c></row>'
                       '</sheetData></worksheet>')
        rows = list(read_rows(path))
        check("shared strings, rich text, inline strings and numbers",
              rows[:3], [["Block", "DistrictID:1"], ["130010001001000", "007"],
                         ["130010001001001", "12"]])
        check("a blank leading cell does not shift the row", rows[3], [None, "5"])
        bef = B.read_block_equivalency(path)
        check("block-equivalency reader parses districts as ints, skipping blank blocks",
              bef, {"130010001001000": 7, "130010001001001": 12})


def committed_cases():
    print("committed artifacts")
    reg = B.load(B.OUTPUT_FILE)
    plans = B.load(B.PLANS_FILE)
    cmp_ = B.load(B.COMPARISON_FILE)
    execs = B.load(B.EXECUTIVE_SEATS_FILE)["seats"]
    check("seats.json validates", registry_errors(reg, plans, cmp_["plans"], execs), [])
    check("seats.json matches a rebuild (run build_seat_registry.py if this fails)",
          B.same_content(B.build_registry(plans, cmp_, execs), reg), True)
    by = {s["id"]: s for s in reg["seats"]}
    check("350 seats: 335 districted, 2 US Senate, 13 statewide",
          (len(by), sum(1 for s in by.values() if s["plan"]),
           sum(1 for s in by.values() if s["body"] == "us-senate-ga"),
           sum(1 for s in by.values() if s["body"] == "ga-executive")), (350, 335, 2, 13))
    c = cmp_["plans"]
    check("measured 2021 -> 2023 carry-over: 5 of 14 / 41 of 56 / 119 of 180",
          [len(c[p]["carriedOver"]) for p in ("us-house-ga-2023", "ga-senate-2023", "ga-house-2023")],
          [5, 41, 119])
    check("today's HD 15 is the 2021 seat", (by["ga-house-15@2021"]["redrawnBy"], "ga-house-15@2023" in by), (None, False))
    check("2021 HD 149 links exactly to 2023 HD 133",
          [l["seatId"] for l in by["ga-house-149@2021"]["successorSeats"]], ["ga-house-133@2023"])
    check("GA-1, 2, 3, 8, 12 carried over unchanged", c["us-house-ga-2023"]["carriedOver"], [1, 2, 3, 8, 12])


def main():
    compare_cases()
    build_cases()
    validation_cases()
    xlsx_cases()
    committed_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll seat-registry checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
