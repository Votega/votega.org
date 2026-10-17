#!/usr/bin/env python3
"""Assert validate_search_corpus.py gates on self-contradiction and only reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships a broken index, and a
legitimate change that gates throws away a good day of data and leaves search
stale. Each case below pins which side of the line a condition falls on.

Usage:
  python scripts/test_search_corpus_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_search_corpus as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def rec(title, category, url=None):
    return {"title": title, "desc": "d", "category": category,
            "url": url or f"x.html?id={title}"}


def build(records):
    cats = {}
    for r in records:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    return {"metadata": {"count": len(records), "categories": cats}, "records": records}


def sound():
    """A small, self-consistent file in the shape generate_search_corpus.py emits."""
    records = [rec(f"Leg {i}", "GA Legislator", f"ga-member.html?id={i}") for i in range(10)]
    records += [rec(f"Race {i}", "Race") for i in range(6)]
    # Shared URL is legitimate: the GA executives all point at one overview page.
    records += [rec("Gov", "GA Executive", "ga-executive.html"),
                rec("LtGov", "GA Executive", "ga-executive.html")]
    return build(records)


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound()
    d["metadata"]["count"] = 99
    check("a count that does not match len(records) is tier 1",
          any("len(records)" in e for e in V.tier1(d)), True)

    # The mirror of the empty-category case below: counts that do not add up are
    # the file contradicting itself, so THIS one gates.
    d = sound()
    d["metadata"]["categories"]["Race"] += 5
    errs = V.tier1(d)
    check("category counts not summing to metadata.count is tier 1",
          any("sums to" in e for e in errs), True)

    d = sound()
    d["metadata"]["categories"]["Race"] -= 1
    d["metadata"]["categories"]["GA Legislator"] += 1
    errs = V.tier1(d)
    check("counts that sum correctly but misattribute a category are tier 1",
          any("categories['Race']" in e for e in errs), True)

    d = sound()
    d["records"].append(rec("Orphan", "Mystery"))
    d["metadata"]["count"] += 1
    d["metadata"]["categories"].pop("Race")
    d["metadata"]["categories"]["GA Legislator"] += 6
    check("a record whose category is not in metadata.categories is tier 1",
          any("'Mystery'" in e and "not in metadata.categories" in e for e in V.tier1(d)), True)

    for field in ("title", "url", "category"):
        d = sound()
        d["records"][0][field] = " "
        check(f"a record with a blank {field} (the client renders it) is tier 1",
              any(f"'{field}'" in e for e in V.tier1(d)), True)

    d = sound()
    del d["records"][0]["desc"]
    check("a record missing desc entirely is tier 1",
          any("'desc'" in e for e in V.tier1(d)), True)
    d = sound()
    d["records"][0]["desc"] = ""
    check("a blank desc is fine (the generator emits it)", V.tier1(d), [])

    d = sound()
    d["records"].append(copy.deepcopy(d["records"][0]))
    d["metadata"]["count"] += 1
    d["metadata"]["categories"]["GA Legislator"] += 1
    check("the same (title, url) twice is tier 1",
          any("duplicates" in e for e in V.tier1(d)), True)
    check("two people sharing one url is NOT a duplicate", V.tier1(sound()), [])

    check("a file with no records list is tier 1", V.tier1({"metadata": {}}) != [], True)


def tier2_cases():
    old = sound()

    # False positive of `assert count >= 200`. This file has 18 records, far under
    # the old floor, and is perfectly sound; the floor would have discarded it.
    check("the old `count >= 200` floor: 18 records is not tier 1 (assert's false positive)",
          V.tier1(old), [])

    # The headline case. A whole category vanishing leaves a self-consistent file
    # -- counts rebuilt from the records, sums matching -- so tier 1 passes it,
    # and tier 2 names it with before and after.
    new = build([r for r in old["records"] if r["category"] != "GA Legislator"])
    check("a whole category going to zero does NOT gate", V.tier1(new), [])
    sections = dict(V.tier2(new, old))
    lines = sections.get("Categories now empty — check these first", [])
    check("...and is reported, naming its before and after",
          lines, ["- **GA Legislator**: 10 → 0"])

    # Why the global floor was blind to it: nothing about the TOTAL moved
    # enough to matter, while the category did.
    big = build(new["records"] + [rec(f"Cand {i}", "Candidate") for i in range(300)])
    check("a total far above the old floor still reports the missing category",
          "Categories now empty — check these first" in dict(V.tier2(big, old)), True)

    new = build(old["records"] + [rec("Z", "Brand New")])
    check("a category appearing is reported",
          dict(V.tier2(new, old)).get("Categories that appeared"), ["- **Brand New**: 0 → 1"])

    new = build([r for r in old["records"] if r["category"] != "Race"] +
                [rec(f"R{i}", "Race") for i in range(2)])
    check("a sharp move is reported with before and after",
          dict(V.tier2(new, old)).get("Categories that moved more than 25%"),
          ["- **Race**: 6 → 2 (-4)"])

    new = build([r for r in old["records"] if r["title"] != "LtGov"])
    check("losing one of two records is not an event", V.tier2(new, old), [])

    check("an unchanged file reports nothing", V.tier2(copy.deepcopy(old), old), [])
    check("no baseline reports nothing (first run)", V.tier2(old, None), [])

    body = V.render("search-entities.json", V.tier2(
        build([r for r in old["records"] if r["category"] != "Race"]), old))
    check("the report states the index was committed anyway",
          "none of them blocked the update" in body, True)
    check("the report points at the load() skip as a likely cause",
          "not found -- skipping" in body, True)
    check("an empty report says so", "No material change this run" in
          V.render("search-entities.json", []), True)


tier1_cases()
tier2_cases()

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
