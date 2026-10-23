#!/usr/bin/env python3
"""Pin the ga-district-information artifacts: the county roll-up must reproduce the
reapportionment office's published county reports, and the gates must refuse bad data.
No network, no token.

Usage:
  python scripts/test_publish_ga_district_information.py

Exits 0 on success, 1 on any failure.
"""

import copy
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_ga_district_information as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def raises(label, fn, fragment):
    try:
        fn()
    except ValueError as e:
        check(label, fragment in str(e), True)
    else:
        check(label, "did not raise", "raised")


arts = P.build_artifacts()
counties = json.loads(arts["data/counties.json"])["counties"]
zips = json.loads(arts["data/zips.json"])


def pop(fips, chamber, district):
    return next(r["population"] for r in counties[fips][chamber] if r["district"] == district)


# Values copied from the Office of Legislative and Congressional Reapportionment's
# county reports (Senate-2023 / House-2023 / Congress-2023), so this test fails if the
# roll-up ever drifts from the official numbers.
check("Appling is wholly Senate 19 (18,444)", pop("001", "state-senate", 19), 18444)
check("Barrow Senate 45 = 39,217 (official county report)", pop("013", "state-senate", 45), 39217)
check("Barrow Senate 46 = 17,116", pop("013", "state-senate", 46), 17116)
check("Barrow Senate 47 = 27,172", pop("013", "state-senate", 47), 27172)
check("Bartow Senate 37 = 11,130", pop("015", "state-senate", 37), 11130)
check("Bartow Senate 52 = 97,771", pop("015", "state-senate", 52), 97771)
check("Appling House 157 = 12,825 and 178 = 5,619",
      (pop("001", "state-house", 157), pop("001", "state-house", 178)), (12825, 5619))
check("Appling is wholly Congress 1 (18,444)", pop("001", "us-house", 1), 18444)
check("Barrow's three Senate districts add to the county",
      sum(r["population"] for r in counties["013"]["state-senate"]), counties["013"]["population"])

check("159 counties", len(counties), 159)
check("county populations add to the statewide total",
      sum(c["population"] for c in counties.values()), 10_711_908)
check("counties list districts in number order",
      all([r["district"] for r in c["state-house"]] == sorted(r["district"] for r in c["state-house"])
          for c in counties.values()), True)

# ---- CSVs agree with the JSON ---------------------------------------------------
def rows(name):
    return list(csv.DictReader(io.StringIO(arts[name].decode())))


zd = rows("data/zip-districts.csv")
n_lists = sum(len(e.get(k) or []) for e in zips["zips"].values() for k in P.ZIP_LISTS)
check("zip-districts.csv has one row per listed district", len(zd), n_lists)
check("zip-districts.csv covers all three chambers", {r["chamber"] for r in zd},
      {"state-senate", "state-house", "us-house"})
check("rank 1 is the largest share in every ZIP/chamber group", all(
    float(r["share"]) >= max(float(x["share"]) for x in zd if x["zip"] == r["zip"] and x["chamber"] == r["chamber"]) - 1e-9
    for r in zd if r["rank"] == "1"), True)
check("no PO-box ZIP appears in the district CSV",
      {r["kind"] for r in zd}.isdisjoint({"po-box"}), True)

cd = rows("data/county-districts.csv")
check("county-districts.csv has one row per county district",
      len(cd), sum(len(c[ch]) for c in counties.values() for ch in P.CHAMBERS.values()))
check("county CSV reproduces Barrow Senate 45",
      [r["population"] for r in cd if r["county_fips"] == "013" and r["chamber"] == "state-senate"
       and r["district"] == "45"], ["39217"])

tracts = json.loads(arts["data/tracts.json"])
td = rows("data/tract-districts.csv")
check("tracts.json holds every tract", len(tracts["tracts"]), 2796)
check("tract CSV has one row per tract district",
      len(td), sum(len(r[k]) for r in tracts["tracts"].values() for k in P.CHAMBERS))

# ---- schemas parse and name their datasets ----------------------------------------
for name in ("zips", "counties", "tracts"):
    s = json.loads(arts[f"data/{name}.schema.json"])
    check(f"{name} schema has an $id pointing at the published repo",
          s["$id"].startswith("https://raw.githubusercontent.com/Votega/ga-district-information/main/"), True)

# ---- licence/notice are emitted by the shared publisher ---------------------------
check("the repo is registered for NOTICE.md", P.REPO in __import__("lib.sibling_publish", fromlist=["x"]).REPO_SOURCES, True)

# ---- the gates refuse bad data ---------------------------------------------------
P.validate(arts)
check("a sound build passes the gate", True, True)

bad = dict(arts)
c2 = json.loads(arts["data/counties.json"]); c2["counties"]["013"]["state-senate"][0]["population"] += 1
bad["data/counties.json"] = json.dumps(c2).encode()
raises("a county whose districts do not add up is refused", lambda: P.validate(bad), "districts sum to")

bad = dict(arts)
c2 = json.loads(arts["data/counties.json"]); c2["metadata"]["totalPopulation"] += 5
bad["data/counties.json"] = json.dumps(c2).encode()
raises("counties that disagree with the tract total are refused", lambda: P.validate(bad), "sum to")

bad = dict(arts)
z2 = json.loads(arts["data/zips.json"]); z2["zips"] = dict(list(z2["zips"].items())[:10])
bad["data/zips.json"] = json.dumps(z2).encode()
raises("a ZIP file with too few ZIPs is refused", lambda: P.validate(bad), "need >=")

bad = dict(arts)
t2 = json.loads(arts["data/tracts.json"]); t2["tracts"] = {}
bad["data/tracts.json"] = json.dumps(t2).encode()
raises("an empty tract file is refused", lambda: P.validate(bad), "need >=")

# ---- district -> county (the county table read from the district's side) ----------------
dc = list(csv.DictReader(io.StringIO(arts["data/district-counties.csv"].decode())))
cd_rows = list(csv.DictReader(io.StringIO(arts["data/county-districts.csv"].decode())))


def dcs(chamber, district):
    return [r for r in dc if r["chamber"] == chamber and r["district"] == str(district)]


check("district-counties uses the 5-digit county FIPS", all(len(r["county_fips"]) == 5 and r["county_fips"].startswith("13") for r in dc), True)
check("Newton is 13217 here and 217 in the county table",
      ("13217" in {r["county_fips"] for r in dc}, "217" in counties), (True, True))
check("one row per county-district pair, same count as county-districts.csv", len(dc), len(cd_rows))
check("county-districts.csv gained a coverage column", cd_rows[0]["coverage"] in ("full", "partial"), True)
check("coverage is full exactly when share_of_county is 1",
      all((r["coverage"] == "full") == (float(r["share_of_county"]) == 1.0) for r in cd_rows + dc), True)
for chamber in ("state-senate", "state-house", "us-house"):
    sums = {}
    for r in dc:
        if r["chamber"] == chamber:
            sums[r["district"]] = sums.get(r["district"], 0) + float(r["share_of_district"])
    check(f"{chamber}: each district's county shares sum to 1", all(abs(v - 1) < 0.005 for v in sums.values()), True)
newton = lambda ch: sorted(int(r["district"]) for r in dc if r["chamber"] == ch and r["county_fips"] == "13217")
check("Newton County is in House 113, 114, 118", newton("state-house"), [113, 114, 118])
check("Newton County is in Senate 42, 43", newton("state-senate"), [42, 43])
check("Newton County is in congressional 10, 13", newton("us-house"), [10, 13])
check("House 113 lies wholly in Newton", [(r["county"], r["share_of_district"]) for r in dcs("state-house", 113)], [("Newton", "1.0")])
check("House 112, House 144 and Senate 25 hold no Newton residents",
      [r for r in dc if r["county_fips"] == "13217" and (r["chamber"], r["district"]) in
       {("state-house", "112"), ("state-house", "144"), ("state-senate", "25")}], [])
bad_fips = copy.deepcopy(arts)
bad_fips["data/district-counties.csv"] = bad_fips["data/district-counties.csv"].replace(b",13217,", b",217,", 1)
raises("a 3-digit county FIPS in district-counties is refused", lambda: P.validate(bad_fips), "5-digit")
bad_share = copy.deepcopy(arts)
_rows = list(csv.reader(io.StringIO(bad_share["data/district-counties.csv"].decode())))
_rows[1][_rows[0].index("share_of_district")] = "0.5"      # first data row's district no longer sums to 1
bad_share["data/district-counties.csv"] = P._csv(_rows[0], _rows[1:])
raises("district shares that stop summing to 1 are refused", lambda: P.validate(bad_share), "sum to 1")

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll checks passed.")
