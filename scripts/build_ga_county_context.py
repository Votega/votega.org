#!/usr/bin/env python3
"""Pull county Census context for the early-vote page from Georgia Civic Data (ACS 5-year, CC BY 4.0).

Writes scripts/data/ga-county-context.json, which generate_ga_early_vote.py reads. A committed snapshot,
not a live fetch: the early-vote generator is a manual local run and should not depend on the network.

Per county and per ACS vintage (the vintage ending in an election's year is the one used for that election):
  adults          residents 18 and over: total population minus under 5 minus ages 5-17 (population_by_age)
  noncitizens     residents who are not U.S. citizens, ALL AGES (foreign_born_population, B05002)
  citizenAdults   adults - noncitizens, an ESTIMATE. B05002 has no age split, so this also subtracts the
                  noncitizen children and runs slightly low; the Census's own citizen voting-age table
                  (B05003) is not in the Georgia Civic Data catalog
  bachelorsPct    share of adults 25+ with a bachelor's degree or higher (educational_attainment)

Usage:  python scripts/build_ga_county_context.py [--vintage 2022 --vintage 2024]
Source: https://georgiacivicdata.org (U.S. Census Bureau, American Community Survey 5-Year Estimates).
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402

API = "https://georgiacivicdata.org/api/v1/census"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ga-county-context.json")
DEFAULT_VINTAGES = ("2022", "2024")
COUNTIES = 159


def fetch_csv(topic, params):
    """GET one county-level slice as CSV -> list of dict rows. Exits on anything but 159 clean rows."""
    q = "&".join(f"{k}={v}" for k, v in {"format": "csv", "detail": "counties", "limit": COUNTIES, **params}.items())
    url = f"{API}/{topic}?{q}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "votega.org build"}), timeout=60) as r:
                rows = list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                sys.exit(f"{url}: HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError):
            pass
    else:
        sys.exit(f"{url}: failed after 3 tries")
    if len(rows) != COUNTIES:
        sys.exit(f"{url}: {len(rows)} rows, expected {COUNTIES}")
    return rows


def by_county(rows, value_col):
    out = {}
    for r in rows:
        if r[value_col] in ("", None):
            sys.exit(f"missing {value_col} for county {r['county_fips']} in {r['year']}: not a complete slice")
        out[r["county_fips"]] = float(r[value_col])
    return out


def build_vintage(year):
    age = {b: by_county(fetch_csv("population_by_age", {"year": year, "age_bracket": b}), "population_count")
           for b in ("all", "under_5", "5_17")}
    nonc = by_county(fetch_csv("foreign_born_population", {
        "year": year, "citizenship_status": "noncitizen", "place_of_birth": "all",
        "region_of_birth": "all", "native_birthplace_detail": "all"}), "population_count")
    bach = by_county(fetch_csv("educational_attainment", {"year": year, "attainment_level": "bachelors"}), "attainment_rate")
    grad = by_county(fetch_csv("educational_attainment", {"year": year, "attainment_level": "graduate"}), "attainment_rate")
    names = {r["county_fips"]: r["county_name"] for r in fetch_csv(
        "population_by_age", {"year": year, "age_bracket": "all"})}
    out = {}
    for fips in sorted(age["all"]):
        adults = int(age["all"][fips] - age["under_5"][fips] - age["5_17"][fips])
        noncit = int(nonc[fips])
        out[fips] = {
            "name": names[fips],
            "adults": adults,
            "noncitizens": noncit,
            "citizenAdults": max(adults - noncit, 0),
            "bachelorsPct": round(100.0 * (bach[fips] + grad[fips]), 1),
        }
    return out


def check(vintage, counties):
    errs = []
    for fips, c in counties.items():
        if c["adults"] <= 0:
            errs.append(f"{c['name']}: no adults")
        if not 0 <= c["bachelorsPct"] <= 100:
            errs.append(f"{c['name']}: bachelor's share {c['bachelorsPct']} out of range")
        if c["noncitizens"] > c["adults"] * 0.6:
            errs.append(f"{c['name']}: {c['noncitizens']:,} noncitizens against {c['adults']:,} adults looks wrong")
    total = sum(c["adults"] for c in counties.values())
    if not 7_500_000 < total < 9_500_000:
        errs.append(f"statewide adults {total:,} is outside the plausible range for Georgia")
    if errs:
        sys.exit(f"{vintage}: " + "; ".join(errs))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", action="append", default=[], help="ACS 5-year vintage end year (repeatable)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    vintages = a.vintage or list(DEFAULT_VINTAGES)
    data = {v: build_vintage(v) for v in vintages}
    for v, counties in data.items():
        check(v, counties)
    merged = {}
    for v, counties in data.items():
        for fips, c in counties.items():
            slot = merged.setdefault(fips, {"name": c["name"]})
            slot[v] = {k: c[k] for k in ("adults", "noncitizens", "citizenAdults", "bachelorsPct")}
    doc = {
        "metadata": {
            "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "U.S. Census Bureau, American Community Survey 5-Year Estimates, via Georgia Civic Data (georgiacivicdata.org)",
            "license": "CC BY 4.0",
            "vintages": vintages,
            "count": len(merged),
            "citizenAdultsNote": "citizenAdults = adults 18+ minus non-citizen residents of ALL ages (B05002 has no age split), "
                                 "so it runs slightly low; an estimate, not the Census citizen voting-age population",
        },
        "counties": merged,
    }
    write_json_atomic(a.out, doc)
    for v, counties in data.items():
        print(f"{v}: {len(counties)} counties, {sum(c['adults'] for c in counties.values()):,} adults, "
              f"{sum(c['citizenAdults'] for c in counties.values()):,} estimated citizen adults")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
