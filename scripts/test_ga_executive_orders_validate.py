#!/usr/bin/env python3
"""Assert validate_ga_executive_orders.py gates on self-contradiction and only reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships broken data, and a
legitimate change that gates throws away a good run and leaves the site stale.
Each case below pins which side of the line a condition falls on.

Usage:
  python scripts/test_ga_executive_orders_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_executive_orders as V  # noqa: E402

failures = []
YEAR = 2026


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def order(num, title, category="Appointment", hashed=True):
    mm, dd, yy = num.split(".")[:3]
    o = {"date": f"20{yy}-{mm}-{dd}", "number": num, "title": title, "category": category,
         "url": f"https://gov.georgia.gov/document/2026-executive-order/{num.replace('.', '')}/download"}
    if hashed:
        o.update({"sha256": "a" * 64, "bytes": 12345, "fetchedAt": "2026-10-14T08:20:00Z",
                  "archiveUrl": None})
    return o


def sound():
    """A small, self-consistent file in the shape fetch/enrich_ga_executive_orders emit."""
    orders = [
        order("10.14.26.01", "Appointing a Judge to the Superior Court"),
        order("10.09.26.02", "Writ of Election for State Senate District 7", "Writ of Election"),
        order("01.05.26.01", "Flags to be lowered to half-staff", "Flag at Half-Staff"),
    ]
    return {"_note": "Sourced from https://gov.georgia.gov/executive-action/executive-orders/2026.",
            "metadata": {"year": YEAR, "governor": "Brian P. Kemp", "updatedAt": "2026-10-14",
                         "source": "https://gov.georgia.gov/executive-action/executive-orders/2026",
                         "count": len(orders)},
            "orders": orders}


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound(), YEAR), [])

    d = sound()
    d["metadata"]["count"] = 99
    check("a count that does not match what it counts is tier 1",
          any("metadata.count" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][0]["title"] = ""
    check("an order with no title is tier 1", any("no title" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][1].pop("number")
    check("an order with no number is tier 1", any("no number" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][1]["number"] = d["orders"][0]["number"]
    check("a duplicate order number is tier 1",
          any("duplicate number" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][0]["number"] = "2026-0042"
    check("a malformed order number is tier 1",
          any("malformed number" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][0]["date"] = "2026-10-15"
    check("a date that disagrees with the number's encoded date is tier 1",
          any("disagrees with the date encoded" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][2]["number"] = "01.05.25.01"
    d["orders"][2]["date"] = "2025-01-05"
    check("a 2025 order in the 2026 file is tier 1",
          any("this is the 2026 file" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["metadata"]["year"] = 2025
    check("metadata.year disagreeing with the file name is tier 1",
          any("file name's year" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["metadata"].pop("year")
    check("a missing metadata.year is tier 1", V.tier1(d, YEAR) != [], True)

    d = sound()
    d["metadata"].pop("updatedAt")
    check("a non-empty file with no updatedAt is tier 1",
          any("updatedAt" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][0]["sha256"] = "not-a-hash"
    check("a malformed sha256 is tier 1", any("sha256" in e for e in V.tier1(d, YEAR)), True)

    d = sound()
    d["orders"][0].pop("bytes")
    check("a hash with no byte size (a half-written enrichment) is tier 1",
          any("bytes" in e for e in V.tier1(d, YEAR)), True)

    check("a non-list orders is tier 1", V.tier1({"metadata": {}, "orders": {}}, YEAR) != [], True)

    # Everything below is the world, or the calendar, and must NOT gate.

    # THE JANUARY FALSE POSITIVE. The old heredoc ran `if not orders: sys.exit(...)`.
    # On 1 January the new year's file is empty until the Governor signs the first
    # order, so that gate failed every twice-daily run for days. It must not return.
    d = sound()
    d["orders"] = []
    d["metadata"] = {"year": YEAR, "governor": "Brian P. Kemp", "count": 0}
    check("an empty year file is NOT tier 1 (the January false positive)", V.tier1(d, YEAR), [])

    d = sound()
    d["orders"] = []
    d["metadata"]["count"] = 0
    check("an empty year file with an updatedAt is NOT tier 1 either", V.tier1(d, YEAR), [])

    # Enrichment is best-effort: a PDF that would not download leaves no hash.
    d = sound()
    for k in ("sha256", "bytes", "fetchedAt", "archiveUrl"):
        d["orders"][0].pop(k)
    check("an order not yet hashed or archived is NOT tier 1", V.tier1(d, YEAR), [])

    # A single-order file is just a quiet year.
    d = sound()
    d["orders"] = d["orders"][:1]
    d["metadata"]["count"] = 1
    check("a file with far fewer orders than last time is NOT tier 1", V.tier1(d, YEAR), [])

    d = sound()
    d["orders"] = list(reversed(d["orders"]))
    check("orders in ascending rather than descending order is NOT tier 1 (2025 is stored so)",
          V.tier1(d, YEAR), [])

    check("tier1 with no year to compare skips the filename check", V.tier1(sound(), None), [])


def tier2_cases():
    old = sound()
    jan = date(2026, 1, 3)
    mid = date(2026, 10, 15)

    check("no change -> nothing to report", V.tier2(sound(), old, today=mid), [])
    check("no baseline -> does not list the whole backlog as new", V.tier2(sound(), None, today=mid), [])

    # New order: named, with its date and number.
    new = copy.deepcopy(old)
    new["orders"].insert(0, order("10.15.26.01", "Suspending the motor fuel tax"))
    new["metadata"]["count"] = 4
    secs = V.tier2(new, old, today=mid)
    heads = [h for h, _ in secs]
    check("a new order is reported", "New executive orders" in heads, True)
    body = V.render("ga-executive-orders-2026.json", secs)
    check("the new order is named with its number and date",
          "10.15.26.01" in body and "2026-10-15" in body and "Suspending the motor fuel tax" in body, True)
    check("a run with only new routine orders says no action is needed",
          "No action needed" in body, True)

    # A writ of election is the corroboration for a vacancy date: not routine.
    new = copy.deepcopy(old)
    new["orders"].insert(0, order("10.16.26.01", "Writ of Election for House District 42", "Writ of Election"))
    new["metadata"]["count"] = 4
    secs = V.tier2(new, old, today=mid)
    check("a new writ of election gets its own section",
          any(h.startswith("Writ of election") for h, _ in secs), True)
    check("a writ of election is not 'no action needed'",
          "No action needed" in V.render("x.json", secs), False)

    # THE OLD GATE'S SHRINKING-COUNT CONDITION. `len(orders) < prev_n` aborted the
    # run. It is a comparison with last run's file, so it reports -- and names what went.
    new = copy.deepcopy(old)
    gone = new["orders"].pop(1)
    new["metadata"]["count"] = 2
    secs = V.tier2(new, old, today=mid)
    check("a shrinking count is reported (the old gate's condition), not gated",
          any(h.startswith("Orders no longer listed") for h, _ in secs), True)
    check("the report names the order that disappeared",
          gone["number"] in V.render("x.json", secs), True)
    check("the shrink report states the totals", "3 -> 2" in V.render("x.json", secs), True)

    # A renumbered order shows up as one gone and one new with the same title.
    new = copy.deepcopy(old)
    new["orders"][1] = order("10.09.26.03", old["orders"][1]["title"], "Writ of Election")
    secs = V.tier2(new, old, today=mid)
    check("a renumbered order is flagged as possibly renumbered",
          "renumbered?" in V.render("x.json", secs), True)

    new = copy.deepcopy(old)
    new["orders"][0]["title"] = "Appointing a different Judge"
    heads = [h for h, _ in V.tier2(new, old, today=mid)]
    check("a retitled order is reported", "Existing orders edited at the source" in heads, True)

    new = copy.deepcopy(old)
    new["orders"][0].pop("sha256")
    heads = [h for h, _ in V.tier2(new, old, today=mid)]
    check("an order missing its hash is reported", "Orders awaiting their PDF hash" in heads, True)
    check("... as routine, not an alarm",
          "No action needed" in V.render("x.json", V.tier2(new, old, today=mid)), True)

    # An empty file. January: expected. Later in the year: worth a look.
    empty = {"metadata": {"year": 2026, "count": 0}, "orders": []}
    secs = V.tier2(empty, None, today=jan, year=2026)
    check("an empty year file in early January is reported as expected",
          bool(secs) and "Expected" in secs[0][1][0], True)
    check("... and is not an alarm", "No action needed" in V.render("x.json", secs), True)
    secs = V.tier2(empty, None, today=mid, year=2026)
    check("an empty current-year file in October is flagged as unexpected",
          bool(secs) and "not** expected" in secs[0][1][0], True)
    check("... and that one is not 'no action needed'",
          "No action needed" in V.render("x.json", secs), False)

    body = V.render("ga-executive-orders-2026.json", V.tier2(new, old, today=mid))
    check("the report states the data was committed anyway", "the data is committed" in body, True)
    check("an empty report says so", "No material change this run" in V.render("x.json", []), True)


def main():
    print("tier 1 - gate on self-contradiction:")
    tier1_cases()
    print("\ntier 2 - report change, never gate:")
    tier2_cases()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
