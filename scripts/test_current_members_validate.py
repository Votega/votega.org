#!/usr/bin/env python3
"""Assert validate_current_members.py gates on self-contradiction, reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships broken data, and a
legitimate change that gates throws away a whole day of it and leaves the site
stale.

Three cases matter most, because they are the conditions the heredoc this
replaces actually gated on, on a DAILY job:

  * a roster under 500 members (`assert count >= 500`)
  * Congress.gov detail fetches failing (`assert failures <= max(5, count*0.05)`)
  * a Georgia member whose inline sponsorship summary is null
    (`assert s is not None`) — the state the pipeline DESIGNS FOR when one page
    of that member's record fails, and which the entity page already handles

All three must be proven tier 2 forever.

Usage:
  python scripts/test_current_members_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_current_members as V  # noqa: E402

failures = []

CONGRESS = 119


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(bid, state="Alabama", chamber="House of Representatives", **kw):
    m = {
        "bioguideId": bid,
        "name": f"Member {bid}",
        "partyName": "Republican",
        "state": state,
        "terms": {"item": [{"chamber": chamber, "startYear": 2025}]},
    }
    m.update(kw)
    return m


def ga_member(bid, sponsored, cosponsored, **kw):
    m = member(bid, state="Georgia", **kw)
    m["sponsorship"] = {"congress": CONGRESS, "sponsored": sponsored,
                        "cosponsored": cosponsored}
    m["recentSponsored"] = [{"n": i} for i in range(min(V.RECENT_CAP, sponsored))]
    return m


def row(n):
    return ["hr", str(1000 + n), f"A bill about {n}", "2025-01-03", "2025-02-01", 0, 0]


def sound():
    """A self-consistent set of the three artifacts, in the shape the run emits.

    A full house would be 541 rows; the roster here is deliberately small, since
    a short roster is tier 2 and must not disturb any tier-1 case. The Georgia
    delegation is complete at 16 so the under-strength path is exercised only
    where a case asks for it.
    """
    ga = [ga_member(f"G{n:03d}", 8, 40) for n in range(1, 17)]
    others = [member(f"X{n:03d}") for n in range(1, 11)]
    members = ga + others
    roster = {
        "metadata": {"count": len(members), "congress": CONGRESS,
                     "enrichmentFailures": 0},
        "members": members,
    }
    counts = {m["bioguideId"]: [8, 40] for m in ga}
    index = {
        "metadata": {"generatedAt": "2026-10-17T06:00:00Z", "congress": CONGRESS,
                     "scope": "GA delegation", "memberCount": len(counts),
                     "totalSponsored": 8 * 16, "totalCosponsored": 40 * 16},
        "members": counts,
    }
    slices = {
        bid: {"bioguideId": bid, "congress": CONGRESS, "actions": [""],
              "policyAreas": [""],
              "primary": [row(i) for i in range(8)],
              "cosponsored": [row(i) for i in range(40)]}
        for bid in counts
    }
    return roster, index, slices


def tier1_cases():
    r, i, s = sound()
    check("a sound set raises nothing", V.tier1(r, i, s), [])

    r, i, s = sound()
    r["metadata"]["count"] = 99
    check("a count that does not match what it counts is tier 1",
          any("metadata.count" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"] = [member(f"X{n:04d}") for n in range(V.SEATS_MAX + 1)]
    r["metadata"]["count"] = len(r["members"])
    i["members"], i["metadata"]["memberCount"] = {}, 0
    i["metadata"]["totalSponsored"] = i["metadata"]["totalCosponsored"] = 0
    check("more members than Congress has seats is tier 1",
          any("more than the" in e and "seats that exist" in e
              for e in V.tier1(r, i, {})), True)

    r, i, s = sound()
    r["members"][0].pop("partyName")
    check("a missing required field is tier 1",
          any("missing required" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"].append(member("G001", state="Georgia"))
    r["metadata"]["count"] = len(r["members"])
    check("a duplicated bioguide ID is tier 1",
          any("duplicate bioguideId" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"][0]["terms"] = {"item": []}
    check("a member with no terms (so no derivable chamber) is tier 1",
          any("no terms.item" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"].append(ga_member("G017", 8, 40))
    r["metadata"]["count"] = len(r["members"])
    check("a 17th Georgia seat is tier 1",
          any("more than the 16 seats" in e for e in V.tier1(r, i, s)), True)

    # ── the sponsorship artifacts against the roster ──
    r, i, s = sound()
    i = None
    check("a missing sponsorship index is tier 1",
          any("was not generated" in e for e in V.tier1(r, i, {})), True)

    r, i, s = sound()
    i["metadata"].pop("generatedAt")
    check("an index with no generatedAt is tier 1 (the panel stamps from it)",
          any("carries no generatedAt" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    i["metadata"]["memberCount"] = 3
    check("memberCount disagreeing with the entries is tier 1",
          any("memberCount" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    i["members"]["Z999"] = [1, 1]
    i["metadata"]["memberCount"] = len(i["members"])
    i["metadata"]["totalSponsored"] += 1
    i["metadata"]["totalCosponsored"] += 1
    check("an index entry for nobody in the roster is tier 1",
          any("not in the Georgia roster" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    i["members"]["G001"] = [9, 40]
    i["metadata"]["totalSponsored"] += 1
    check("the index disagreeing with the inline summary is tier 1",
          any("!= inline summary" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"][0]["sponsorship"]["congress"] = CONGRESS - 1
    check("a summary for a different Congress than the index is tier 1",
          any("is for Congress" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    s["G001"] = None
    check("a promised slice file that is missing is tier 1",
          any("missing or unreadable" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    s["G001"]["primary"] = s["G001"]["primary"][:3]
    check("a slice row count disagreeing with the summary is tier 1",
          any("rows, summary says" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    s["G001"]["primary"][0] = ["hr", "1", "t"]
    check("a slice row that is not 7 fields is tier 1",
          any("not 7 fields" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    s["G001"]["primary"][0][2] = ""
    check("a slice row with no title is tier 1",
          any("missing type/number/title" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"][0]["recentSponsored"] = [{"n": n} for n in range(V.RECENT_CAP + 1)]
    check("recentSponsored over its own cap is tier 1",
          any("more than the 20" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    r["members"][0]["recentSponsored"] = [{"n": 1}]
    check("recentSponsored disagreeing with min(20, sponsored) is tier 1",
          any("its own summary implies" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    i["metadata"]["totalSponsored"] = 1
    check("an index total that does not sum its own entries is tier 1",
          any("summed over its own entries" in e for e in V.tier1(r, i, s)), True)

    r, i, s = sound()
    i["members"], i["metadata"]["memberCount"] = {}, 0
    i["metadata"]["totalSponsored"] = i["metadata"]["totalCosponsored"] = 0
    check("an empty index while the roster claims sponsorship is tier 1",
          any("index is empty but the roster" in e for e in V.tier1(r, i, {})), True)

    r, i, s = sound()
    r["members"] = []
    check("an empty roster is tier 1", V.tier1(r, i, s) != [], True)

    # ── everything below is the world moving, and must NOT gate ──
    #
    # These are the three conditions the old heredoc failed the run on. Each one
    # aborted the job before the commit step and discarded the whole day's
    # refresh, which dies with the runner.
    r, i, s = sound()
    r["members"] = r["members"][:17]        # 16 GA + 1, far under any floor
    r["metadata"]["count"] = len(r["members"])
    check("a roster far under 500 members is NOT tier 1 "
          "(the old `count >= 500` floor's false positive)", V.tier1(r, i, s), [])

    r, i, s = sound()
    r["metadata"]["enrichmentFailures"] = len(r["members"])
    check("every detail fetch failing is NOT tier 1 (an upstream outage, "
          "and the old `failures <= 5%` gate's false positive)", V.tier1(r, i, s), [])

    # The headline one. A null summary is what fetch_member_legislation() returns
    # when one page of that member's record fails, on purpose, rather than
    # publishing a truncated list as fact. The entity page reads it as "no tab".
    r, i, s = sound()
    r["members"][0]["sponsorship"] = None
    r["members"][0].pop("recentSponsored")
    dropped = i["members"].pop("G001")
    s.pop("G001")
    i["metadata"]["memberCount"] = len(i["members"])
    i["metadata"]["totalSponsored"] -= dropped[0]
    i["metadata"]["totalCosponsored"] -= dropped[1]
    check("a member's sponsorship coming back null is NOT tier 1 "
          "(the old `s is not None` gate's false positive)", V.tier1(r, i, s), [])

    r, i, s = sound()
    for m in r["members"][:3]:
        m["sponsorship"] = None
        m.pop("recentSponsored")
        gone = i["members"].pop(m["bioguideId"])
        s.pop(m["bioguideId"])
        i["metadata"]["totalSponsored"] -= gone[0]
        i["metadata"]["totalCosponsored"] -= gone[1]
    i["metadata"]["memberCount"] = len(i["members"])
    check("three of sixteen slices missing is NOT tier 1 "
          "(the old `len(counts) >= 14` floor's edge)", V.tier1(r, i, s), [])

    r, i, s = sound()
    r["members"] = [m for m in r["members"] if m["bioguideId"] != "G016"]
    r["metadata"]["count"] = len(r["members"])
    gone = i["members"].pop("G016")
    s.pop("G016")
    i["metadata"]["memberCount"] = len(i["members"])
    i["metadata"]["totalSponsored"] -= gone[0]
    i["metadata"]["totalCosponsored"] -= gone[1]
    check("a vacant Georgia seat is NOT tier 1", V.tier1(r, i, s), [])

    # A Congress three weeks old. The old floors were 100 sponsored / 500
    # cosponsored, which every January run would have failed.
    r, i, s = sound()
    for m in r["members"][:16]:
        m["sponsorship"] = {"congress": CONGRESS, "sponsored": 0, "cosponsored": 0}
        m["recentSponsored"] = []
        i["members"][m["bioguideId"]] = [0, 0]
        s[m["bioguideId"]] = {"primary": [], "cosponsored": []}
    i["metadata"]["totalSponsored"] = i["metadata"]["totalCosponsored"] = 0
    check("a brand-new Congress with nothing introduced yet is NOT tier 1 "
          "(the old record floors' false positive)", V.tier1(r, i, s), [])


def tier2_cases():
    r, i, s = sound()

    check("no baseline and nothing unusual -> only the short-roster note",
          [h for h, _ in V.tier2(r, i)], ["Congress below a full house"])

    # Each of the three old gates must now produce a REPORT LINE, so the human
    # sees what the gate used to hide.
    heads = [h for h, _ in V.tier2(r, i)]
    check("a short roster is reported", "Congress below a full house" in heads, True)

    n = copy.deepcopy(r)
    n["metadata"]["enrichmentFailures"] = 40
    heads = [h for h, _ in V.tier2(n, i)]
    check("failed detail fetches are reported",
          "Congress.gov detail fetches that failed" in heads, True)

    n = copy.deepcopy(r)
    n["members"][0]["sponsorship"] = None
    heads = [h for h, _ in V.tier2(n, i)]
    check("a null sponsorship summary is reported",
          "Sponsorship record not published this run" in heads, True)

    n = copy.deepcopy(i)
    n["metadata"]["totalSponsored"] = 4
    heads = [h for h, _ in V.tier2(r, n)]
    check("a thin sponsorship record is reported",
          "Delegation sponsorship record is thin" in heads, True)

    n = copy.deepcopy(r)
    n["members"] = [m for m in n["members"] if m["bioguideId"] != "G016"]
    heads = [h for h, _ in V.tier2(n, i)]
    check("a vacant Georgia seat is reported",
          "Georgia delegation below full strength" in heads, True)

    n = copy.deepcopy(r)
    n["members"].append(member("X999"))
    heads = [h for h, _ in V.tier2(n, i, r, i)]
    check("roster churn is reported", "Members added or removed" in heads, True)

    n = copy.deepcopy(r)
    n["members"][0]["partyName"] = "Democratic"
    heads = [h for h, _ in V.tier2(n, i, r, i)]
    check("a party switch is reported", "Party changed" in heads, True)

    n = copy.deepcopy(i)
    n["metadata"]["congress"] = CONGRESS + 1
    heads = [h for h, _ in V.tier2(r, n, r, i)]
    check("a Congress rollover is reported", "Congress rolled over" in heads, True)

    n = copy.deepcopy(i)
    n["members"].pop("G001")
    heads = [h for h, _ in V.tier2(r, n, r, i)]
    check("a dropped slice is reported", "Sponsorship slice dropped" in heads, True)

    n = copy.deepcopy(i)
    n["members"]["G001"] = [2, 10]
    heads = [h for h, _ in V.tier2(r, n, r, i)]
    check("counts going down is reported", "Sponsorship counts went down" in heads, True)

    # The report is what a human reads; it must say the data shipped anyway.
    body = V.render(V.tier2(r, i))
    check("the report states the data was committed anyway",
          "none of them blocked the update" in body, True)
    check("an empty report says so",
          "no material change this run" in V.render([]), True)


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
