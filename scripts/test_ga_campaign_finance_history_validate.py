#!/usr/bin/env python3
"""Assert validate_ga_campaign_finance_history.py gates on self-contradiction and only reports change.

Each case pins which side of the line a condition falls on. The "OLD FLOOR"
cases prove the heredoc's gates (`len(filers) < 1200`, `min(cycleYears) > 2020`)
no longer fire.

Usage:
  python scripts/test_ga_campaign_finance_history_validate.py

Exits 0 on success, 1 on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_campaign_finance_history as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def rec(fid, cid, year, office="State Senator", district="4"):
    return {"recordId": f"{fid}:{cid}", "filerEntityId": fid, "electionCycleId": cid,
            "source": "legacy", "office": office, "district": district,
            "totalRaised": 10.0, "cycleYear": year}


def build(records):
    filers = {r["recordId"]: r for r in records}
    by_year, by_office = {}, {}
    for k, r in filers.items():
        if r["cycleYear"] is not None:
            by_year.setdefault(str(r["cycleYear"]), []).append(k)
        by_office.setdefault(r["office"], []).append(k)
    return {"metadata": {"count": len(filers), "cycleYears": sorted(by_year)},
            "filers": filers, "byCycleYear": by_year, "byOffice": by_office,
            "bySeat": {}, "byNormalizedName": {}}


def sound():
    recs = [rec(str(i), 1, 2022) for i in range(6)]
    recs += [rec(str(i), 2, 2024) for i in range(4)]
    recs += [rec("90", 3, 2018, "Governor", None), rec("91", 3, 2018, "Governor", None)]
    return build(recs)


def heads(sections):
    return [h for h, _ in sections]


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound()
    d["metadata"]["count"] = 99
    check("a count that does not match len(filers) is tier 1",
          any("metadata.count" in e for e in V.tier1(d)), True)

    for field in V.REQUIRED_FIELDS:
        d = sound()
        del d["filers"]["3:1"][field]
        check(f"a record (not the first) missing {field} is tier 1",
              any("missing required fields" in e for e in V.tier1(d)), True)

    d = sound()
    d["filers"]["3:1"]["source"] = "peachfile"
    check("one record not tagged legacy is tier 1 (the old check sampled only the first)",
          any("source=legacy" in e for e in V.tier1(d)), True)

    # Keying collapsed to bare filer ids: per-cycle rows overwrite each other.
    recs = []
    for r in [rec(str(i), 1, 2022) for i in range(6)]:
        r["recordId"] = r["filerEntityId"]
        recs.append(r)
    d = build(recs)
    check("keys collapsed to bare filer ids is tier 1",
          any("no composite" in e for e in V.tier1(d)), True)

    d = sound()
    d["filers"]["wrong:key"] = d["filers"].pop("3:1")
    check("a key that is not its own record's id is tier 1",
          any("keyed other than" in e for e in V.tier1(d)), True)

    d = sound()
    d["byCycleYear"]["2022"].append("999:9")
    check("an index naming a missing record is tier 1",
          any("not in filers" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["cycleYears"] = ["2022"]
    check("metadata.cycleYears disagreeing with byCycleYear is tier 1",
          any("cycleYears" in e for e in V.tier1(d)), True)

    check("an empty file is tier 1", V.tier1(build([])) != [], True)

    # ── the world moving: must NOT gate ──
    # OLD FLOORS. sound() has 12 records and cycle years 2018-2024: the heredoc's
    # `len(filers) < 1200` rejected it, and `min(years) > 2020` rejects a file
    # that starts at 2022. Neither is a contradiction.
    check("OLD FLOOR len(filers) < 1200 does NOT gate", V.tier1(sound()), [])
    d = build([rec(str(i), 1, 2022) for i in range(6)] + [rec("7", 2, 2024)])
    check("OLD FLOOR min(cycleYears) > 2020 does NOT gate",
          min(int(y) for y in d["metadata"]["cycleYears"]) > 2020 and V.tier1(d) == [], True)

    # A null cycleYear is a record the Commission named oddly (the real file has
    # two); it is not a contradiction.
    d = sound()
    d["filers"]["3:1"]["cycleYear"] = None
    d["byCycleYear"]["2022"].remove("3:1")
    check("a record with a null cycleYear is NOT tier 1", V.tier1(d), [])


def tier2_cases():
    old = sound()

    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline -> nothing to report", V.tier2(sound(), None), [])

    # The failure the 1200 floor was groping at: a year/office silently empty.
    new = build([r for r in old["filers"].values() if r["cycleYear"] != 2024])
    out = V.tier2(new, old)
    check("a cycle year vanishing entirely is reported and named",
          any("2024" in l and "gone entirely" in l
              for h, ls in out if h.startswith("Cycle years that lost") for l in ls), True)

    new = build([r for r in old["filers"].values() if r["office"] != "Governor"])
    out = V.tier2(new, old)
    check("an office returning nothing is reported by name (zero keys are absent)",
          any("Governor" in l and "2 → 0" in l
              for h, ls in out if h.startswith("Offices that lost") for l in ls), True)

    new = build(list(old["filers"].values()) + [rec("50", 1, 2022)])
    check("a backfilled record is reported as a gain",
          any(h.startswith("Cycle years that gained") for h in heads(V.tier2(new, old))), True)

    # One removed, one added, same year and office: counts balance, identity moved.
    recs = [r for r in old["filers"].values() if r["recordId"] != "0:1"] + [rec("77", 1, 2022)]
    check("a swapped record is reported though the counts balance",
          "Records swapped" in heads(V.tier2(build(recs), old)), True)

    body = V.render("h.json", V.tier2(build(recs), old))
    check("the report states the data was committed anyway",
          "None of it blocked the update" in body, True)
    check("an empty report says so", "No material change this run" in V.render("h.json", []), True)


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
