#!/usr/bin/env python3
"""Pin the district -> county table: every population adds up, the committed files are what
the builder produces, and Newton County (the Georgia Civic Data pilot) comes out right.
No network.

Usage:
  python scripts/test_district_counties.py

Exits 0 on success, 1 on any failure.
"""

import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_district_counties as B  # noqa: E402
from lib.ga_county_fips import GA_COUNTY_FIPS  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


table = json.load(open(B.TRACTS_FILE, encoding="utf-8"))
out = B.build(table)
districts, counties = out["districts"], out["counties"]

print("shape")
check("district counts", out["metadata"]["districtCounts"], {"senate": 56, "house": 180, "congress": 14})
check("159 counties, all real FIPS", sorted(counties) == sorted(GA_COUNTY_FIPS.values()), True)
check("total population is the 2020 Georgia count", out["metadata"]["totalPopulation"], 10711908)

print("arithmetic")
county_total = {f: sum(t["p"] for g, t in table["tracts"].items() if g[:5] == f) for f in counties}
for key, chamber in B.CHAMBERS:
    want = {}
    for t in table["tracts"].values():
        for d, n in t[key].items():
            want[int(d)] = want.get(int(d), 0) + n
    got = {int(d): sum(r["population"] for r in rows) for d, rows in districts[chamber].items()}
    check(f"{chamber}: each district's county populations sum to the district total", got, want)
    per_county = {}
    for rows in districts[chamber].values():
        for r in rows:
            per_county[r["fips"]] = per_county.get(r["fips"], 0) + r["population"]
    check(f"{chamber}: each county's district populations sum to the county total", per_county, county_total)
    check(f"{chamber}: shares of a district sum to 1 (within rounding)",
          all(abs(sum(r["shareOfDistrict"] for r in rows) - 1) < 0.002 for rows in districts[chamber].values()), True)
check("coverage is full exactly when the county's whole population is in the district",
      all((r["coverage"] == "full") == (r["shareOfCounty"] == 1.0)
          for ch in districts.values() for rows in ch.values() for r in rows), True)

print("committed files")
check("JSON is what the builder produces", json.load(open(B.OUT_JSON, encoding="utf-8")), json.loads(json.dumps(out)))
buf = io.StringIO()
w = csv.writer(buf, lineterminator="\n")
w.writerow(B.CSV_FIELDS)
w.writerows(B.csv_rows(out))
check("CSV is what the builder produces", open(B.OUT_CSV, encoding="utf-8", newline="").read(), buf.getvalue())

print("Newton County (13217)")
n = counties["13217"]
check("name", n["name"], "Newton")
check("House districts", [d["district"] for d in n["house"]], [113, 114, 118])
check("Senate districts", [d["district"] for d in n["senate"]], [42, 43])
check("congressional districts", sorted(d["district"] for d in n["congress"]), [10, 13])
check("House 113 lies wholly in Newton", districts["house"]["113"][0]["shareOfDistrict"], 1.0)
check("the ZIP-based pilot list's House 112 and 144 and Senate 25 hold no Newton residents",
      [c for c in ("112", "144") if any(r["fips"] == "13217" for r in districts["house"][c])]
      + [c for c in ("25",) if any(r["fips"] == "13217" for r in districts["senate"][c])], [])

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all passed")
