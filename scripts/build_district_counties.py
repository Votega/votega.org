#!/usr/bin/env python3
"""
Build assets/data/ga-district-counties.{json,csv}: which Georgia counties each Senate, House
and congressional district covers, and how much of each county each district holds.

A legislative district is not a county. Most House districts, and many Senate and
congressional ones, take part of a county, so a flat "district -> counties" list would
overstate who represents what. Every row therefore carries the population on both sides of
the join:

  population        2020 residents of the county who live in this district
  shareOfDistrict   population / the district's total       (how much of the district is here)
  shareOfCounty     population / the county's total         (how much of the county this seat holds)
  coverage          "full" when the whole county sits in this district, else "partial"

The table is geography only, keyed by chamber and district number, so a vacant or suspended
seat still has its counties; join to ga-members.json on (chamber, district) for the person.
County FIPS are the 5-digit state-plus-county codes (13001 ...), the key Georgia Civic Data
uses for every county-grain fact.

Source: scripts/data/ga-tract-districts.json, which scripts/build_ga_tract_district_table.py
builds from the General Assembly's Senate-2023, House-2023 and Congress-2023 block-equivalency
files and 2020 Census block populations. A tract's first five digits are its county FIPS.
Nothing else is read, so the output changes only when that table does (i.e. at redistricting);
generatedAt is copied from it for the same reason, which keeps the build idempotent.

Usage:
    python scripts/build_district_counties.py
"""

import csv
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib.atomic_io import atomic_write, write_json_atomic  # noqa: E402

ROOT = os.path.dirname(HERE)
TRACTS_FILE = os.path.join(HERE, "data", "ga-tract-districts.json")
OUT_JSON = os.path.join(ROOT, "assets", "data", "ga-district-counties.json")
OUT_CSV = os.path.join(ROOT, "assets", "data", "ga-district-counties.csv")

# tract-table key -> published chamber name
CHAMBERS = (("s", "senate"), ("h", "house"), ("c", "congress"))
CSV_FIELDS = ("chamber", "district", "county_fips", "county_name", "population",
              "share_of_district", "share_of_county", "coverage")


def build(table):
    """Return the output object for an already-loaded tract table."""
    names = table["counties"]                     # {"001": "Appling", ...}
    tracts = table["tracts"]

    county_total = defaultdict(int)               # fips5 -> residents
    pop = {key: defaultdict(lambda: defaultdict(int)) for key, _ in CHAMBERS}   # key -> district -> fips5 -> n
    district_total = {key: defaultdict(int) for key, _ in CHAMBERS}

    for geoid, t in tracts.items():
        fips = geoid[:5]
        county_total[fips] += t["p"]
        for key, _ in CHAMBERS:
            for district, n in t[key].items():
                pop[key][int(district)][fips] += n
                district_total[key][int(district)] += n

    def row(key, district, fips, n):
        return {
            "fips": fips,
            "name": names[fips[2:]],
            "population": n,
            "shareOfDistrict": round(n / district_total[key][district], 4),
            "shareOfCounty": round(n / county_total[fips], 4),
            "coverage": "full" if n == county_total[fips] else "partial",
        }

    districts, counties = {}, {}
    for key, chamber in CHAMBERS:
        districts[chamber] = {}
        for district in sorted(pop[key]):
            rows = [row(key, district, f, n) for f, n in pop[key][district].items()]
            rows.sort(key=lambda r: (-r["population"], r["fips"]))
            districts[chamber][str(district)] = rows
            for r in rows:
                entry = counties.setdefault(r["fips"], {"name": r["name"], "senate": [], "house": [], "congress": []})
                entry[chamber].append({"district": district, "population": r["population"],
                                       "shareOfCounty": r["shareOfCounty"],
                                       "shareOfDistrict": r["shareOfDistrict"],
                                       "coverage": r["coverage"]})
    for entry in counties.values():
        for _, chamber in CHAMBERS:
            entry[chamber].sort(key=lambda d: (-d["population"], d["district"]))

    meta = table["metadata"]
    return {
        "metadata": {
            "generatedAt": meta["generatedAt"],
            "source": "VoteGA, derived from scripts/data/ga-tract-districts.json: " + meta["source"],
            "plans": meta["plans"],
            "populationBasis": meta["censusVintage"],
            "districtCounts": {chamber: len(districts[chamber]) for _, chamber in CHAMBERS},
            "countyCount": len(counties),
            "totalPopulation": sum(county_total.values()),
            "fields": {
                "population": "2020 residents of the county who live in the district",
                "shareOfDistrict": "population / the district's total population",
                "shareOfCounty": "population / the county's total population",
                "coverage": "full when the whole county lies in the district, otherwise partial",
            },
            "note": ("Geography only: join to ga-members.json on (chamber, district) for the "
                     "member. Shares are 2020 population shares under the plans named above; "
                     "they must be rebuilt if Georgia redraws."),
        },
        "districts": districts,
        "counties": dict(sorted(counties.items())),
    }


def csv_rows(out):
    for _, chamber in CHAMBERS:
        for district, rows in out["districts"][chamber].items():
            for r in rows:
                yield [chamber, int(district), r["fips"], r["name"], r["population"],
                       r["shareOfDistrict"], r["shareOfCounty"], r["coverage"]]


def main():
    with open(TRACTS_FILE, encoding="utf-8") as f:
        out = build(json.load(f))
    write_json_atomic(OUT_JSON, out, indent=1, ensure_ascii=False)
    with atomic_write(OUT_CSV, newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CSV_FIELDS)
        w.writerows(csv_rows(out))
    m = out["metadata"]
    print(f"Wrote {OUT_JSON}: {m['districtCounts']} districts across {m['countyCount']} counties")
    return 0


if __name__ == "__main__":
    sys.exit(main())
