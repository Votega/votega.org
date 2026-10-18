#!/usr/bin/env python3
"""Pin the ZIP -> district arithmetic and the committed lookup tables. No network,
no HUD token: the crosswalk rows are fabricated, the tables are the committed ones.

Usage:
  python scripts/test_ga_zip_districts.py

Exits 0 on success, 1 on any failure.
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_ga_zip_districts as G  # noqa: E402
import validate_ga_zip_districts as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def close(label, got, want, tol=1e-4):
    check(label, abs(got - want) <= tol, True)


# ---- the committed tables -------------------------------------------------------
TRACTS = G.load_json(G.TRACT_TABLE)
USPS = G.load_json(G.USPS_ZIPS)
meta = TRACTS["metadata"]

check("tract table covers the 2020 census population", meta["totalPopulation"], 10_711_908)
check("tract table has every Georgia tract", len(TRACTS["tracts"]), 2796)
check("tract table has all 159 counties", len(TRACTS["counties"]), 159)
check("every tract's Senate split sums to its population",
      all(sum(r["s"].values()) == r["p"] for r in TRACTS["tracts"].values()), True)
check("every tract's House split sums to its population",
      all(sum(r["h"].values()) == r["p"] for r in TRACTS["tracts"].values()), True)
valid = V.valid_districts(TRACTS)
check("56 Senate districts", len(valid["s"]), 56)
check("180 House districts", len(valid["h"]), 180)
check("14 congressional districts", len(valid["c"]), 14)
check("every tract's congressional split sums to its population",
      all(sum(r["c"].values()) == r["p"] for r in TRACTS["tracts"].values()), True)
check("USPS table: standard + PO-box = count",
      USPS["metadata"]["standard"] + USPS["metadata"]["poBox"], USPS["metadata"]["count"])
check("USPS table holds only Georgia ZIPs (no 37316)", "37316" in USPS["zips"], False)

# ---- the arithmetic, on a toy world ---------------------------------------------
# Tract A: 100 people, all Senate 1; House 10 holds 80 and House 11 holds 20.
# Tract B: 300 people, Senate 1 holds 100 and Senate 2 holds 200; all House 11.
# Tract C: empty (no residents) but wholly in Senate 9 / House 90.
# Tract D: 50 people, Senate 3 and House 12.
toy = {
    "metadata": {"plans": {"s": "S", "h": "H"}, "censusVintage": "toy"},
    "counties": {"001": "Alpha", "002": "Beta"},
    "tracts": {
        "13001000100": {"p": 100, "s": {"001": 100}, "h": {"010": 80, "011": 20}, "c": {"005": 60, "004": 40}},
        "13001000200": {"p": 300, "s": {"001": 100, "002": 200}, "h": {"011": 300}, "c": {"005": 300}},
        "13002000300": {"p": 0, "s": {}, "h": {}, "c": {}},
        "13002000400": {"p": 50, "s": {"003": 50}, "h": {"012": 50}, "c": {"012": 50}},
    },
}
usps = {"zips": {"30001": "standard", "30002": "po-box", "30003": "standard", "30004": "standard"}}


def row(z, geoid, res, tot=None, city="ALPHA TOWN"):
    return {"zip": z, "geoid": geoid, "city": city, "state": "GA",
            "res_ratio": res, "bus_ratio": 0, "oth_ratio": 0, "tot_ratio": res if tot is None else tot}


hud = {
    "zip-tract": [
        row("30001", "13001000100", 0.25), row("30001", "13001000200", 0.75),
        row("30002", "13001000100", 1.0),
        # 30004: half its addresses sit in an empty tract, which must not count.
        row("30004", "13001000100", 0.5), row("30004", "13002000300", 0.5),
        # 30099: HUD has it, USPS's Georgia list does not.
        row("30099", "13002000400", 1.0, city="ODD CITY"),
    ],
    "zip-county": [
        row("30001", "13001", 1.0), row("30004", "13001", 0.5), row("30004", "13002", 0.5),
        row("30099", "13002", 1.0),
    ],
}
entries = G.build_entries(hud, toy, usps)

e = entries["30001"]
# Senate 1: .25*100/100 + .75*100/300 = .5 ; Senate 2: .75*200/300 = .5
check("Senate shares combine tract weights with tract splits",
      [(r["district"], r["share"]) for r in e["stateSenate"]], [(1, 0.5), (2, 0.5)])
# House 10: .25*.8 = .2 ; House 11: .25*.2 + .75*1 = .8
check("House shares are ranked largest first",
      [(r["district"], r["share"]) for r in e["stateHouse"]], [(11, 0.8), (10, 0.2)])
# Congress 5: .25*.6 + .75*1 = .9 ; Congress 4: .25*.4 = .1
check("congressional shares use the same tract method, ranked",
      [(r["district"], r["share"]) for r in e["usHouse"]], [(5, 0.9), (4, 0.1)])
check("county names are attached", e["counties"], [{"fips": "001", "name": "Alpha", "share": 1.0}])
check("the HUD city is title-cased for display", e["city"], "Alpha Town")

check("a PO-box ZIP carries no districts",
      (entries["30002"]["kind"], entries["30002"]["stateHouse"], entries["30002"]["counties"]),
      ("po-box", None, None))

e4 = entries["30004"]
check("an empty tract adds no district (renormalised over residents)",
      [(r["district"], r["share"]) for r in e4["stateSenate"]], [(1, 1.0)])
check("a ZIP in the USPS list but absent from HUD is kept, with no districts",
      (entries["30003"]["kind"], entries["30003"]["stateHouse"]), ("standard", None))
check("a ZIP only HUD knows is kept as other, not dropped",
      (entries["30099"]["kind"], [r["district"] for r in entries["30099"]["stateHouse"]]),
      ("other", [12]))

# A sliver is listed, never cut off.
sliver = copy.deepcopy(toy)
sliver["tracts"]["13001000100"] = {"p": 1_000_000, "s": {"001": 999_999, "004": 1},
                                   "h": {"010": 999_999, "013": 1}, "c": {"001": 1_000_000}}
sl = G.build_entries({"zip-tract": [row("30001", "13001000100", 1.0)], "zip-county": []},
                     sliver, {"zips": {"30001": "standard"}})["30001"]
check("a one-in-a-million sliver is still listed",
      [r["district"] for r in sl["stateSenate"]], [1, 4])
check("and never rounds to zero", sl["stateSenate"][1]["share"] >= G.SHARE_FLOOR, True)

# Weight fallback for a business-only ZIP.
biz = G.build_entries({"zip-tract": [row("30001", "13001000100", 0.0, tot=1.0)], "zip-county": []},
                      toy, {"zips": {"30001": "standard"}})["30001"]
check("a ZIP with no residential addresses falls back to the total ratio",
      [r["district"] for r in biz["stateHouse"]], [10, 11])

# ---- the validator --------------------------------------------------------------
many = {f"31{n:03d}": copy.deepcopy(e) for n in range(850)}
doc = G.build_document(many, "2026", "2", toy, "2026-01-01T00:00:00+00:00")
vt = V.valid_districts(toy)
vt = {"s": {1, 2, 3}, "h": {10, 11, 12}, "c": {4, 5, 12}}
check("a sound document passes tier 1", V.tier1(doc, vt), [])

bad = copy.deepcopy(doc); bad["zips"]["31000"]["kind"] = "po-box"
check("a PO-box ZIP carrying districts is an error",
      any("PO-box ZIP carries" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc); bad["zips"]["31000"]["stateHouse"][0]["share"] = 0.3
check("shares that do not sum to 1 are an error",
      any("sum to" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc); bad["zips"]["31000"]["stateHouse"].reverse()
check("an unranked list is an error", any("not ranked" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc); bad["zips"]["31000"]["stateSenate"][0]["district"] = 57
check("a district the plan does not have is an error",
      any("no such district" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc); bad["zips"]["31000"]["usHouse"][0]["district"] = 15
check("a congressional district the plan does not have is an error",
      any("usHouse: no such district" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc); bad["zips"]["31000"]["stateSenate"] = None
check("a Senate list without a House list is an error",
      any("disagree" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc)
for z in list(bad["zips"])[:200]:
    bad["zips"][z]["stateHouse"] = bad["zips"][z]["stateSenate"] = bad["zips"][z]["usHouse"] = None
check("a collapsed join is an error", any("collapsed" in x for x in V.tier1(bad, vt)), True)

bad = copy.deepcopy(doc); bad["metadata"]["count"] = 1
check("a wrong count is an error", any("metadata.count" in x for x in V.tier1(bad, vt)), True)
check("too few ZIPs is an error",
      any("floor" in x for x in V.tier1(G.build_document(dict(list(many.items())[:10]), "2026", "2", toy, "x"), vt)),
      True)

old = copy.deepcopy(doc); new = copy.deepcopy(doc)
new["zips"]["31000"]["stateHouse"] = [{"district": 10, "share": 0.8}, {"district": 11, "share": 0.2}]
check("tier 2 reports a changed largest district",
      any("largest" in x and "31000" in x for x in V.tier2(new, old)), True)
check("tier 2 says nothing changed when nothing did", V.tier2(doc, copy.deepcopy(doc)), ["No material change."])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll checks passed.")
