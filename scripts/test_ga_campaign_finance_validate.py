#!/usr/bin/env python3
"""Assert validate_ga_campaign_finance.py gates on self-contradiction and only reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships broken finance data, and
a legitimate change that gates throws away a good week of it. Each case pins
which side of the line a condition falls on, and the "OLD FLOORS" block proves
the heredoc's gates (`seats < 150`, `legislative < 400`) no longer fire.

Usage:
  python scripts/test_ga_campaign_finance_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_campaign_finance as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


H, S = "House of Representatives", "Senate"


def filer(fid, office, district=None, raised=100.0):
    return {"filerEntityId": fid, "office": office, "district": district,
            "totalRaised": raised}


def build(filers):
    """Assemble a file the way generate_ga_campaign_finance.py does."""
    by_seat, by_office = {}, {}
    for fid, f in filers.items():
        chamber = V.LEGISLATIVE.get(f["office"])
        if chamber and f["district"]:
            by_seat.setdefault(f"{chamber}-{f['district']}", []).append(fid)
        else:
            by_office.setdefault(f["office"], []).append(fid)
    return {"metadata": {"count": len(filers), "cycle": 2026,
                         "rowsFetched": len(filers), "incompleteOffices": [],
                         "droppedOverrides": []},
            "filers": filers, "bySeat": by_seat, "byOffice": by_office,
            "byNormalizedName": {f"person {fid}": fid for fid in filers}}


def sound():
    filers = {}
    for n in range(1, 11):
        filers[str(n)] = filer(str(n), "State Representative", str(n))
    for n in range(1, 5):
        filers[str(100 + n)] = filer(str(100 + n), "State Senator", str(n))
    for n in range(5):
        filers[str(200 + n)] = filer(str(200 + n), "Governor")
    return build(filers)


def heads(sections):
    return [h for h, _ in sections]


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound()
    d["metadata"]["count"] = 99
    check("a count that does not match len(filers) is tier 1",
          any("metadata.count" in e for e in V.tier1(d)), True)

    d = sound()
    del d["filers"]["1"]["totalRaised"]
    check("a filer missing totalRaised is tier 1",
          any("required field" in e for e in V.tier1(d)), True)

    d = sound()
    del d["filers"]["1"]["office"]
    check("a filer missing office is tier 1",
          any("required field" in e for e in V.tier1(d)), True)

    d = sound()
    d["filers"]["1"]["totalRaised"] = None
    check("totalRaised present but None is NOT tier 1 (None is a value)", V.tier1(d), [])

    d = sound()
    d["bySeat"][f"{H}-1"].append("999999")
    check("a seat naming a filer the file lacks is tier 1",
          any("not in filers" in e for e in V.tier1(d)), True)

    d = sound()
    d["byOffice"]["Governor"].append("999999")
    check("an office naming a filer the file lacks is tier 1",
          any("byOffice" in e for e in V.tier1(d)), True)

    d = sound()
    d["byNormalizedName"]["ghost"] = "999999"
    check("a name index pointing outside filers is tier 1",
          any("byNormalizedName" in e for e in V.tier1(d)), True)

    d = sound()
    d["bySeat"][f"{H}-2"].remove("2")
    check("a legislative filer its own seat index forgot is tier 1",
          any("absent from their own bySeat" in e for e in V.tier1(d)), True)

    d = sound()
    d["bySeat"][f"{H}-3"].remove("3")
    d["bySeat"][f"{H}-4"].append("3")
    check("a legislative filer filed under the wrong seat is tier 1",
          any("absent from their own bySeat" in e for e in V.tier1(d)), True)

    # n == 0: tier 1 on purpose -- an empty run has no good data to discard.
    d = build({})
    check("an empty file is tier 1", V.tier1(d) != [], True)

    # ── the world moving: must NOT gate ──
    # OLD FLOORS: `len(by_seat) < 150` and `len(legislative) < 400` aborted the
    # job on the sound() file below -- 14 seats, 14 legislative filers -- and on
    # any cycle that simply has fewer filers. They gate no longer.
    check("OLD FLOOR seats < 150 does NOT gate", V.tier1(sound()), [])
    d = sound()
    check("OLD FLOOR legislative < 400 does NOT gate",
          sum(1 for f in d["filers"].values() if f["office"] in V.LEGISLATIVE) < 400
          and V.tier1(d) == [], True)

    d = sound()
    for fid in [k for k, f in d["filers"].items() if f["office"] == "State Senator"]:
        del d["filers"][fid]
    d["bySeat"] = {k: v for k, v in d["bySeat"].items() if not k.startswith(S)}
    d["byNormalizedName"] = {k: v for k, v in d["byNormalizedName"].items() if v in d["filers"]}
    d["metadata"]["count"] = len(d["filers"])
    check("a whole chamber with no filers (a partial pull) is NOT tier 1", V.tier1(d), [])

    d = sound()
    d["metadata"]["incompleteOffices"] = ["Governor"]
    d["metadata"]["droppedOverrides"] = ["x -> filerEntityId 1"]
    check("the generator reporting trouble is NOT tier 1", V.tier1(d), [])


def tier2_cases():
    old = sound()

    check("no change -> nothing to report", V.tier2(sound(), old), [])

    # No baseline: the uncovered seats are named, not counted.
    out = V.tier2(sound(), None)
    check("no baseline names the seats that have no filer",
          "Seats with no filer" in heads(out)
          and "House 11, 12" in out[0][1][0] and "Senate 5, 6" in out[0][1][0], True)

    # A seat that had a filer and lost it: named, with chamber.
    new = copy.deepcopy(old)
    del new["filers"]["7"]
    new["bySeat"].pop(f"{H}-7")
    new["metadata"]["count"] -= 1
    out = V.tier2(new, old)
    check("a seat that lost its filer is reported",
          "Seats that lost coverage — check these first" in heads(out), True)
    lost = dict(out)["Seats that lost coverage — check these first"]
    check("the report NAMES the seat rather than counting",
          any("House 7" in l for l in lost), True)
    check("and the standing uncovered list rides along only when something changed",
          any("Currently with no filer" in l for l in lost), True)

    # Standing state is not news: the same uncovered seats as last week report nothing.
    check("unchanged coverage reports nothing even with seats uncovered",
          V.tier2(copy.deepcopy(old), old), [])

    # The chamber-wide collapse: every Senate seat at once.
    new = copy.deepcopy(old)
    for n in range(1, 5):
        del new["filers"][str(100 + n)]
        new["bySeat"].pop(f"{S}-{n}")
    out = V.tier2(new, old)
    lost = dict(out)["Seats that lost coverage — check these first"]
    check("a vanished chamber names every seat", "Senate 1, 2, 3, 4" in lost[0], True)

    new = copy.deepcopy(old)
    new["filers"]["50"] = filer("50", "State Representative", "50")
    new["bySeat"][f"{H}-50"] = ["50"]
    check("a seat gaining a filer is reported",
          "Seats that gained coverage" in heads(V.tier2(new, old)), True)

    # An office that thinned out. Governor 5 -> 2 is 60%.
    new = copy.deepcopy(old)
    for n in (200, 201, 202):
        del new["filers"][str(n)]
    new["byOffice"]["Governor"] = ["203", "204"]
    out = V.tier2(new, old)
    check("an office losing most of its filers is reported",
          any(h.startswith("Offices that lost") for h in heads(out)), True)

    # An office that vanished entirely has no key in a records-tallied map; the
    # union with the baseline is what lets this fire.
    new = copy.deepcopy(old)
    for n in range(5):
        del new["filers"][str(200 + n)]
    new["byOffice"] = {}
    out = V.tier2(new, old)
    thinned = [l for h, ls in out if h.startswith("Offices that lost") for l in ls]
    check("an office that vanished entirely is still named (zero keys are absent)",
          any("Governor" in l and "5 → 0" in l for l in thinned), True)

    # One filer fewer in a tiny office is not a thinning.
    new = copy.deepcopy(old)
    del new["filers"]["200"]
    new["byOffice"]["Governor"].remove("200")
    check("one filer leaving a five-filer office is not reported",
          any(h.startswith("Offices that lost") for h in heads(V.tier2(new, old))), False)

    new = copy.deepcopy(old)
    new["metadata"]["incompleteOffices"] = ["State Senator"]
    out = V.tier2(new, old)
    check("an office the generator says it could not finish is named",
          "Fetch stopped on a failed page" in heads(out)
          and "State Senator" in dict(out)["Fetch stopped on a failed page"][0], True)

    new = copy.deepcopy(old)
    new["metadata"]["droppedOverrides"] = ["ga-house-1-2026-d-3 -> filerEntityId 106587"]
    out = V.tier2(new, old)
    check("a dropped override is named, not fatal",
          any("106587" in l for l in dict(out)["Overrides dropped: the filer no longer exists"]),
          True)

    new = copy.deepcopy(old)
    new["metadata"]["cycle"] = 2028
    check("a cycle change is reported", "Cycle changed" in heads(V.tier2(new, old)), True)

    body = V.render("ga-campaign-finance.json", V.tier2(new, old))
    check("the report states the data was committed anyway",
          "none of them blocked the update" in body, True)
    check("an empty report says so",
          "No material change this run" in V.render("x.json", []), True)


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
