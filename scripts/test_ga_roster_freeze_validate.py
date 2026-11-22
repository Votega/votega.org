#!/usr/bin/env python3
"""Pin the freeze-ga-roster gate (validate_ga_roster_freeze.py).

The freeze cannot be repeated, so the gate must refuse a roster that is short,
doubled, missing fields, or for the wrong biennium -- and must NOT refuse the real
shape: departed members as extra records, a Suspended member, a Vacant placeholder.

Usage:
  python scripts/test_ga_roster_freeze_validate.py

Exits 0 on success, 1 on any failure.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_ga_roster_freeze as F  # noqa: E402

failures = []
HOUSE = "House of Representatives"


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def has(errors, text):
    return any(text in e for e in errors)


def mem(chamber, district, **kw):
    m = {"id": "x", "name": f"{chamber} {district}", "chamber": chamber, "district": district}
    m.update(kw)
    return m


def recount(d):
    for i, m in enumerate(d["members"]):
        m["id"] = f"id-{i}"
    d["metadata"]["count"] = len(d["members"])
    return d


def roster(extra=()):
    members = ([mem("Senate", n) for n in range(1, 57)]
               + [mem(HOUSE, n) for n in range(1, 181)] + list(extra))
    return recount({"metadata": {"session": "2025_26"}, "members": members})


print("a whole roster")
check("56 + 180 passes", F.check(roster(), "2025-2026"), [])
check("blank slug means the current biennium", F.check(roster()), [])

print("departed people are extra records, never seats")
d = roster([mem("Senate", 3, status="Resigned"), mem(HOUSE, 9, status="Removed"),
            mem(HOUSE, 9, status="Deceased")])
check("Resigned/Removed/Deceased beside the holder pass", F.check(recount(d)), [])
d = roster()
d["members"][0]["status"] = "Suspended"
check("a Suspended member still holds the seat", F.check(d), [])
d = roster()
d["members"][0].update(status="Vacant", name="Vacant")
check("a Vacant placeholder holds the seat", F.check(d), [])

print("a short roster must fail")
d = roster()
del d["members"][5]
e = F.check(recount(d))
check("55 senators fails", has(e, "Senate: 55 seats accounted for"), True)
check("names the missing district", has(e, "no entry for district(s) 6"), True)
d = roster()
d["members"] = d["members"][:-1]
check("179 representatives fails", has(F.check(recount(d)), f"{HOUSE}: 179"), True)
d = roster()
d["members"][0]["status"] = "Resigned"   # departed with NO placeholder: seat unaccounted
check("a departed member with no placeholder fails", has(F.check(d), "Senate: 55"), True)
check("an empty roster fails",
      F.check({"metadata": {"session": "2025_26"}, "members": []}) != [], True)

print("a duplicated roster must fail")
e = F.check(roster([mem("Senate", 7)]))
check("a second current senator in district 7 fails", has(e, "duplicate district"), True)
check("...and the seat total is wrong", has(e, "Senate: 57"), True)
d = roster()
d["members"][1]["district"] = 1   # 56 seats, but district 1 doubled and 2 uncovered
e = F.check(d)
check("56 seats with a doubled district fails", has(e, "duplicate district"), True)
check("...and the uncovered district is named", has(e, "no entry for district(s) 2"), True)
check("a district past the chamber size fails",
      has(F.check(roster([mem(HOUSE, 181)])), "outside 1-180"), True)

print("structure and labelling")
d = roster()
del d["members"][0]["name"]
check("a missing required field fails", has(F.check(d), "missing required"), True)
d = roster()
d["metadata"]["count"] = 99
check("metadata.count disagreeing fails", has(F.check(d), "metadata.count"), True)
d = roster()
d["metadata"]["session"] = "2027_28"
check("a 2027-28 roster cannot be filed as 2025-2026",
      has(F.check(d, "2025-2026"), "metadata.session"), True)
check("session_tag", [F.session_tag("2025-2026"), F.session_tag("2026-ss"), F.session_tag("")],
      ["2025_26", None, None])

print("CLI: ::error and non-zero exit")
with tempfile.TemporaryDirectory() as tmp:
    good, bad = os.path.join(tmp, "good.json"), os.path.join(tmp, "bad.json")
    with open(good, "w") as fh:
        json.dump(roster(), fh)
    short = roster()
    del short["members"][0]
    with open(bad, "w") as fh:
        json.dump(recount(short), fh)
    script = os.path.join(HERE, "validate_ga_roster_freeze.py")

    def run(path, *extra):
        return subprocess.run([sys.executable, script, "--members", path, *extra],
                              capture_output=True, text=True)

    check("whole roster exits 0", run(good, "2025-2026").returncode, 0)
    r = run(bad, "2025-2026")
    check("short roster exits 1", r.returncode, 1)
    check("short roster emits ::error", "::error::freeze refused" in r.stdout, True)
    check("unreadable roster exits 1", run(os.path.join(tmp, "missing.json")).returncode, 1)

print("the live committed roster passes (the shape the real freeze will see)")
live = os.path.join(HERE, "..", "assets", "data", "ga-members.json")
if os.path.exists(live):
    with open(live, encoding="utf-8") as fh:
        check("assets/data/ga-members.json", F.check(json.load(fh), "2025-2026"), [])

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nAll passed")
