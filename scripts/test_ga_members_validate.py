#!/usr/bin/env python3
"""Assert validate_ga_members.py gates on self-contradiction and only reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships a broken roster, and a
legitimate change that gates throws away a whole day of it and leaves the site
stale. Each case below pins which side of the line a condition falls on.

The case that matters most is a chamber below full strength. The heredoc this
replaces asserted `len(senate) == 56` / `len(house) == 180`, so a single vacant
seat — a resignation, a death, a seat awaiting a special election — aborted the
job before the commit step and discarded every other member's fresh data with
it. That must be tier 2 forever.

Usage:
  python scripts/test_ga_members_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_members as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(chamber, district, **kw):
    m = {
        "id": f"ocd-person/{chamber[0].lower()}{district:03d}",
        "name": f"{chamber.split()[0]} Member {district}",
        "chamber": chamber,
        "district": district,
        "party": "Republican" if district % 2 else "Democratic",
        "status": None,
    }
    m.update(kw)
    return m


def sound():
    """A full-strength roster in the shape generate_ga_members_soap.py emits.

    Both chambers exactly filled, plus the four statewide executives that sit in
    this file under chamber "executive" and count against no chamber's seats.
    """
    members = ([member("Senate", n) for n in range(1, 57)]
               + [member("House of Representatives", n) for n in range(1, 181)]
               + [{"id": "ocd-person/gov", "name": "The Governor", "chamber": "executive",
                   "district": None, "party": "Republican", "status": None,
                   "title": "Governor"}])
    return {
        "metadata": {"generatedAt": "2026-10-17T07:00:00+00:00", "count": len(members),
                     "session": "2025_26", "jurisdiction": "Georgia"},
        "members": members,
    }


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound()
    d["metadata"]["count"] = 99
    check("a count that does not match what it counts is tier 1",
          any("metadata.count" in e for e in V.tier1(d)), True)

    d = sound()
    d["members"][0].pop("district")
    check("a member missing a required field is tier 1",
          any("missing required" in e for e in V.tier1(d)), True)

    # 181 House members is not a fact about Georgia — the constitution creates
    # 180 seats. Only a broken join or a twice-applied override can produce it.
    d = sound()
    d["members"].append(member("House of Representatives", 181))
    d["metadata"]["count"] = len(d["members"])
    check("a chamber ABOVE its constitutional size is tier 1",
          any("more than the 180 that exist" in e for e in V.tier1(d)), True)

    d = sound()
    d["members"].append(member("Senate", 7, id="ocd-person/duplicate"))
    d["metadata"]["count"] = len(d["members"])
    errs = V.tier1(d)
    check("two members holding one district is tier 1",
          any("duplicate district" in e for e in errs), True)

    # The overrides layer is the only thing that knows a member has left, so a
    # silent failure to apply it republishes a departed member as sitting.
    d = sound()
    overrides = {"_inject": [{"id": "ga-senate-7-vacant", "name": "Vacant"}]}
    check("an _inject entry missing from the output is tier 1",
          any("_inject entries missing" in e for e in V.tier1(d, overrides)), True)
    # The placeholder stands in for the seat the departed member held, so it
    # replaces them rather than adding to the chamber.
    d = sound()
    d["members"] = [m for m in d["members"]
                    if not (m["chamber"] == "Senate" and m["district"] == 7)]
    d["members"].append({"id": "ga-senate-7-vacant", "name": "Vacant",
                         "chamber": "Senate", "district": 7, "status": "Vacant"})
    d["metadata"]["count"] = len(d["members"])
    check("an _inject entry that did apply is not tier 1", V.tier1(d, overrides), [])

    d = sound()
    d["members"] = []
    d["metadata"]["count"] = 0
    check("an empty file is tier 1", V.tier1(d) != [], True)

    # Everything below is the world moving, and must NOT gate. The first is the
    # exact condition the old `assert len(senate) == 56` fired on.
    d = sound()
    d["members"] = [m for m in d["members"]
                    if not (m["chamber"] == "Senate" and m["district"] == 7)]
    d["metadata"]["count"] = len(d["members"])
    check("a vacant Senate seat is NOT tier 1 (the old assert's false positive)",
          V.tier1(d), [])

    d = sound()
    d["members"] = [m for m in d["members"]
                    if not (m["chamber"] == "House of Representatives"
                            and m["district"] in (13, 14, 15))]
    d["metadata"]["count"] = len(d["members"])
    check("three vacant House seats are NOT tier 1", V.tier1(d), [])

    # A departed member is kept in the file so their earlier votes still join by
    # OCD id; their successor holds the seat. Counting both would push the
    # chamber over its maximum, which is why only current seats are counted.
    d = sound()
    d["members"].append(member("House of Representatives", 20,
                               id="ocd-person/departed", status="Resigned",
                               statusDate="2026-03-13"))
    d["metadata"]["count"] = len(d["members"])
    check("a Resigned member alongside their successor is NOT tier 1", V.tier1(d), [])

    # A suspended member still holds the seat, so they count toward it and the
    # chamber stays exactly full.
    d = sound()
    d["members"][60]["status"] = "Suspended"
    check("a Suspended member still fills their seat", V.tier1(d), [])

    d = sound()
    d["members"][0]["party"] = None
    d["members"][1]["district"] = 300
    check("an unknown party and a surprising district are NOT tier 1", V.tier1(d), [])


def tier2_cases():
    old = sound()

    check("a full-strength roster with no change reports nothing",
          V.tier2(sound(), old), [])
    check("a full-strength roster and no baseline reports nothing",
          V.tier2(sound(), None), [])

    # Every member who has left during the biennium keeps an entry, so the
    # standing status roster is a dozen lines long on a day when nothing
    # happened. It is context, never a trigger: as its own section it would make
    # every daily run produce a non-empty report, open a tracking issue forever,
    # and bury the days something actually moved.
    quiet = copy.deepcopy(old)
    quiet["members"] = [m for m in quiet["members"]
                        if not (m["chamber"] == "Senate" and m["district"] == 7)]
    quiet["members"].append(member("Senate", 7, id="ocd-person/successor"))
    quiet["members"].append(member("Senate", 7, id="ocd-person/departed",
                                   status="Resigned", statusDate="2026-03-13"))
    quiet["metadata"]["count"] = len(quiet["members"])
    check("a seat refilled after a departure is self-consistent", V.tier1(quiet), [])
    check("standing departures alone do NOT make a report",
          V.tier2(quiet, quiet), [])
    check("...nor without a baseline", V.tier2(quiet, None), [])

    # The headline: the condition that used to abort the run now reports, names
    # the empty district, and lets the commit proceed.
    new = copy.deepcopy(old)
    new["members"] = [m for m in new["members"]
                      if not (m["chamber"] == "Senate" and m["district"] == 7)]
    new["metadata"]["count"] = len(new["members"])
    sections = V.tier2(new, old)
    heads = [h for h, _ in sections]
    check("a vacant seat is reported", "Chamber below full strength" in heads, True)
    body = "\n".join(l for _, lines in sections for l in lines)
    check("the report names the empty district", "district(s) with no entry: 7" in body, True)
    check("a vacancy is reported without a baseline too",
          "Chamber below full strength" in [h for h, _ in V.tier2(new, None)], True)
    check("the roster change is reported alongside it",
          "Members added or removed" in heads, True)

    new = copy.deepcopy(old)
    new["members"][0]["status"] = "Resigned"
    new["members"][0]["statusDate"] = "2026-10-01"
    heads = [h for h, _ in V.tier2(new, old)]
    check("a departure is reported", "Status changed" in heads, True)
    check("a departure also shows up as a seat short",
          "Chamber below full strength" in heads, True)
    check("the standing status list rides along as context",
          "For reference: members carrying a status" in heads, True)

    new = copy.deepcopy(old)
    new["members"][0]["party"] = "Democratic"
    check("a party switch is reported",
          "Party changed" in [h for h, _ in V.tier2(new, old)], True)

    new = copy.deepcopy(old)
    new["members"][0]["district"] = 2
    new["members"][1]["district"] = 1
    check("a district swap is reported",
          "District changed" in [h for h, _ in V.tier2(new, old)], True)

    new = copy.deepcopy(old)
    new["members"][0]["chamber"] = "House of Representatives"
    new["members"][0]["district"] = 181
    check("a member moving chamber is reported",
          "Chamber changed" in [h for h, _ in V.tier2(new, old)], True)

    # The report is what a human reads; it must say the data shipped.
    new = copy.deepcopy(old)
    new["members"][0]["party"] = "Democratic"
    report = V.render("ga-members.json", V.tier2(new, old))
    check("the report states the data was committed anyway",
          "none of them blocked the update" in report, True)
    check("an empty report says so",
          "no material change this run" in V.render("ga-members.json", []), True)


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
