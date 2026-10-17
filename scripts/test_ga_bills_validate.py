#!/usr/bin/env python3
"""Assert validate_ga_bills.py gates on self-contradiction and only reports change.

A check in the wrong tier is the bug: a self-contradiction that only gets reported
ships broken data, and a legitimate change that gates throws away a good sweep.
Each case pins which side of the line a condition falls on.

Usage:
  python scripts/test_ga_bills_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_bills as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def bill(n, session, chamber="lower"):
    return {"id": f"gga-bill/{n}", "identifier": f"HB {n}", "session": session,
            "chamber": chamber, "title": f"Bill {n}", "billUrl": f"https://x/{n}",
            "status": "Introduced"}


def sound():
    """A small, self-consistent file in the shape generate_ga_bills_soap.py emits."""
    bills = [bill(i, "2025_26") for i in range(1, 11)] + \
            [bill(i, "2026_ss", "upper") for i in range(101, 104)]
    return {
        "metadata": {
            "biennium": "2025-2026",
            "sessions": [{"id": "2025_26", "billCount": 10},
                         {"id": "2026_ss", "billCount": 3}],
            "activeSession": "2026_ss", "session": "2026_ss",
            "totalBills": len(bills), "updateMode": "incremental",
            "fetchedSessions": ["2026_ss"], "preservedSessions": ["2025_26"],
        },
        "bills": bills,
    }


def heads(sections):
    return [h for h, _ in sections]


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound()
    d["metadata"]["totalBills"] = 99
    check("a total that does not match the bills is tier 1",
          any("totalBills" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["sessions"][1]["billCount"] = 176   # claims more than the file holds
    check("a session whose billCount disagrees with the file is tier 1",
          any("session 2026_ss" in e for e in V.tier1(d)), True)

    # The failure the old whole-file 20% shrink gate could not see: the active
    # session is ~3% of the file, so losing ALL of it never moved the total past
    # 20%. The producer's own per-session claim still names it.
    d = sound()
    d["bills"] = [b for b in d["bills"] if b["session"] != "2026_ss"]
    d["metadata"]["totalBills"] = len(d["bills"])
    check("an active session silently lost under a consistent total is tier 1",
          any("session 2026_ss" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"] = [b for b in d["bills"] if b["session"] != "2025_26"]
    d["metadata"]["totalBills"] = len(d["bills"])
    d["metadata"]["sessions"][0]["billCount"] = 0
    check("a preserved session with no bills is tier 1",
          any("marked preserved" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"].append(bill(500, "2027_28"))
    d["metadata"]["totalBills"] = len(d["bills"])
    check("a bill tagged with an unlisted session is tier 1",
          any("does not list" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"].append(copy.deepcopy(d["bills"][0]))
    d["metadata"]["totalBills"] = len(d["bills"])
    d["metadata"]["sessions"][0]["billCount"] += 1
    check("a duplicated bill id is tier 1",
          any("duplicate" in e for e in V.tier1(d)), True)

    for field in V.BILL_REQUIRED:
        d = sound()
        d["bills"][0].pop(field)
        check(f"a bill missing {field} is tier 1",
              any("missing required" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"] = []
    check("an empty file is tier 1", V.tier1(d) != [], True)

    # Everything below is the world moving and must NOT gate.
    d = sound()
    d["bills"] = [b for b in d["bills"] if b["session"] != "2026_ss"]
    d["metadata"]["totalBills"] = len(d["bills"])
    d["metadata"]["sessions"][1]["billCount"] = 0
    check("an honestly empty active session is NOT tier 1", V.tier1(d), [])

    # The old gate: a shrink of more than 20% against HEAD (reset by --scope-key
    # on a rollover). A new biennium legitimately starts a fraction of the size.
    new = sound()
    new["bills"] = [dict(b, session="2027_28") for b in new["bills"][:3]]
    new["metadata"].update(sessions=[{"id": "2027_28", "billCount": 3}], session="2027_28",
                           activeSession="2027_28", totalBills=3, preservedSessions=[])
    check("a rollover shrinking the file by 80% is NOT tier 1 "
          "(the old 20%-shrink gate's false positive)", V.tier1(new), [])

    d = sound()
    d["bills"] = d["bills"][:11] + d["bills"][12:]       # one fewer, metadata honest
    d["metadata"]["totalBills"] = len(d["bills"])
    d["metadata"]["sessions"][1]["billCount"] = 2
    check("a session that lost bills but agrees with itself is NOT tier 1", V.tier1(d), [])

    d = sound()
    d["bills"][0]["chamber"] = "joint"
    check("an unfamiliar chamber value is NOT tier 1", V.tier1(d), [])


def tier2_cases():
    old = sound()
    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline -> nothing beyond the file's own facts", V.tier2(sound(), None), [])

    new = sound()
    new["bills"] = [b for b in new["bills"] if b["session"] != "2026_ss"]
    new["metadata"]["sessions"][1]["billCount"] = 0
    check("an empty active session is reported",
          "The active session holds no bills" in heads(V.tier2(new, None)), True)

    new = sound()
    new["bills"].append(bill(104, "2026_ss", "upper"))
    check("a session gaining bills is reported",
          "A session's bill count changed" in heads(V.tier2(new, old)), True)

    new = sound()
    new["bills"] = new["bills"][1:]
    check("a bill leaving the file is reported",
          "Bills left the file" in heads(V.tier2(new, old)), True)

    new = sound()
    new["metadata"].update(session="2027_28", activeSession="2027_28")
    check("an active-session change is reported",
          "The active session changed" in heads(V.tier2(new, old)), True)

    new = sound()
    new["bills"] = [dict(b, session="2027_28") for b in new["bills"]]
    check("sessions arriving and leaving are reported",
          "Sessions in the file changed" in heads(V.tier2(new, old)), True)

    new = sound()
    new["bills"][0]["chamber"] = "joint"
    check("an unfamiliar chamber is reported",
          "Chamber values the site does not filter on" in heads(V.tier2(new, None)), True)

    new = sound()
    for b in new["bills"]:
        b["status"] = "Signed by Governor"
    check("routine status churn is NOT reported", V.tier2(new, old), [])

    check("an empty report says so",
          "No material change this run" in V.render("ga-bills.json", []), True)
    new = sound()
    new["bills"] = new["bills"][1:]
    check("the report states the data was committed anyway",
          "none of them blocked the update" in V.render("ga-bills.json", V.tier2(new, old)),
          True)


def main():
    print("tier 1 — gate on self-contradiction:")
    tier1_cases()
    print("\ntier 2 — report change, never gate:")
    tier2_cases()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
