#!/usr/bin/env python3
"""Publish Georgia district crosswalks to the Votega/ga-district-information repo.

Three datasets, from the same reconciled source, each as JSON + CSV + JSON Schema:

  ZIP code -> districts        assets/data/ga-zip-districts.json
      data/zips.json                every ZIP: counties and state Senate / state House /
                                    U.S. House districts it TOUCHES, ranked by estimated
                                    share of residents (passthrough of the site's file)
      data/zip-districts.csv        one row per (ZIP, chamber, district)
      data/zip-counties.csv         one row per (ZIP, county)
      data/zips.schema.json

  County -> districts          derived from scripts/data/ga-tract-districts.json
      data/counties.json            each county's 2020 population in each district
      data/county-districts.csv     one row per (county, chamber, district); `coverage` is
                                    "full" when the whole county lies in that district
      data/district-counties.csv    the same table read from the district's side: one row per
                                    (chamber, district, county) with the share of the DISTRICT
                                    in that county as well as the share of the county

Every county code in every file is the 5-digit state+county FIPS (13013), the form the Census
and Georgia Civic Data use; the source tables keep the 3-digit suffix (013) and it is widened here.
      data/counties.schema.json

  Census tract -> districts    scripts/data/ga-tract-districts.json
      data/tracts.json              each tract's 2020 population in each district: the
                                    ingredient the other two are built from, for anyone
                                    who wants a different geography (a school district, a
                                    precinct set, their own service area)
      data/tract-districts.csv      one row per (tract, chamber, district)
      data/tracts.schema.json

The tract and county tables are exact: the tract table is built only if its roll-up
reproduces the reapportionment office's published packet totals and county reports to
the person (see build_ga_tract_district_table.py), so the county table published here
matches those official county reports row for row.

Dry run (no GA_DISTRICT_INFORMATION_TOKEN): writes to $OUT_DIR (default ./out).
See lib/sibling_publish.
"""
import csv
import io
import json
import os
import sys

from lib.sibling_publish import build_json, min_items, publish_or_dry_run

REPO = "Votega/ga-district-information"
TOKEN_ENV = "GA_DISTRICT_INFORMATION_TOKEN"
SCHEMA_VERSION = "2.0.0"   # 2.0.0: every county code is the 5-digit FIPS (13013), not the 3-digit suffix (013);
#                            # 1.1.0: + data/district-counties.csv, + coverage column on county-districts.csv

HERE = os.path.dirname(os.path.abspath(__file__))
ZIPS_SRC = os.path.join(HERE, "..", "assets", "data", "ga-zip-districts.json")
TRACTS_SRC = os.path.join(HERE, "data", "ga-tract-districts.json")

#: tract-table key -> (name used in the published files, plan name key in metadata.plans)
CHAMBERS = {"s": "state-senate", "h": "state-house", "c": "us-house"}
#: Georgia's state FIPS. The source tables key counties on the 3-digit suffix; everything published
#: carries the full 5-digit code (13013), the form the Census and Georgia Civic Data use.
GA_STATE_FIPS = "13"


def fips5(code):
    """The 5-digit county FIPS for a source table's 3-digit county code (or for a 5-digit one)."""
    code = str(code)
    full = code if len(code) == 5 else GA_STATE_FIPS + code
    if len(full) != 5 or not full.startswith(GA_STATE_FIPS) or not full.isdigit():
        raise ValueError(f"not a Georgia county code: {code!r}")
    return full
#: ga-zip-districts.json list key -> the same public chamber name
ZIP_LISTS = {"stateSenate": "state-senate", "stateHouse": "state-house", "usHouse": "us-house"}
#: floors: Georgia has ~880 delivery ZIPs, 159 counties and 2,796 tracts
MIN_ZIPS, MIN_COUNTIES, MIN_TRACTS = 800, 159, 2796


def compact_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode()


# ---- ZIP code -> districts --------------------------------------------------------

def zips_doc(zips):
    """The site's ZIP file with each county code widened to the 5-digit FIPS. The source file keeps
    the 3-digit suffix because the site's own scripts read it, so the change is made here only."""
    out = json.loads(json.dumps(zips))
    for e in out["zips"].values():
        for c in e.get("counties") or []:
            c["fips"] = fips5(c["fips"])
    return out


def zip_districts_csv(doc):
    rows = []
    for z, e in sorted(doc["zips"].items()):
        for key, chamber in ZIP_LISTS.items():
            for rank, r in enumerate(e.get(key) or [], start=1):
                rows.append([z, e.get("city"), e["kind"], chamber, r["district"], r["share"], rank])
    return _csv(["zip", "city", "kind", "chamber", "district", "share", "rank"], rows)


def zip_counties_csv(doc):
    rows = []
    for z, e in sorted(doc["zips"].items()):
        for rank, r in enumerate(e.get("counties") or [], start=1):
            rows.append([z, e.get("city"), e["kind"], fips5(r["fips"]), r["name"], r["share"], rank])
    return _csv(["zip", "city", "kind", "county_fips", "county", "share", "rank"], rows)


# ---- County and tract tables --------------------------------------------------------

def county_table(tracts):
    """{fips: {name, population, <chamber>: [{district, population, share}]}} from the
    tract table, keyed by the 5-digit county FIPS (the first five characters of a tract id)."""
    names = tracts["counties"]
    pop = {}
    by = {}
    for tract_id, rec in tracts["tracts"].items():
        fips = tract_id[:5]                          # state 13 + county
        pop[fips] = pop.get(fips, 0) + rec["p"]
        for key in CHAMBERS:
            bucket = by.setdefault(fips, {}).setdefault(key, {})
            for district, p in rec[key].items():
                bucket[district] = bucket.get(district, 0) + p
    out = {}
    for fips in sorted(pop):
        entry = {"name": names.get(fips[2:]), "population": pop[fips]}
        for key, chamber in CHAMBERS.items():
            entry[chamber] = [
                {"district": int(d), "population": p,
                 "share": round(p / pop[fips], 5) if pop[fips] else None}
                for d, p in sorted(by[fips][key].items(), key=lambda kv: int(kv[0]))
            ]
        out[fips] = entry
    return out


def counties_doc(tracts):
    meta = tracts["metadata"]
    return {
        "metadata": {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": meta["generatedAt"],
            "source": meta["source"],
            "censusVintage": meta["censusVintage"],
            "plans": meta["plans"],
            "count": len(tracts["counties"]),
            "totalPopulation": meta["totalPopulation"],
            "note": "For each county, the 2020 population living in each district of each plan, "
                    "and that as a share of the county. Districts are listed in number order. "
                    "A county in several districts appears once per district. Matches the "
                    "Office of Legislative and Congressional Reapportionment's county reports.",
        },
        "counties": county_table(tracts),
    }


def coverage(population, county_population):
    """"full" when every resident of the county lives in the district, else "partial"."""
    return "full" if population == county_population else "partial"


def county_districts_csv(doc):
    rows = []
    for fips, c in doc["counties"].items():
        for chamber in CHAMBERS.values():
            for r in c[chamber]:
                rows.append([fips, c["name"], chamber, r["district"], r["population"], r["share"],
                             coverage(r["population"], c["population"])])
    return _csv(["county_fips", "county", "chamber", "district", "population", "share_of_county",
                 "coverage"], rows)


def district_counties_rows(doc):
    """One row per (chamber, district, county), from the county table's other side. Population
    is the county's residents inside the district; the share of the district divides by the
    district's total. County FIPS is the full 5-digit code (state 13 + county)."""
    total = {}
    for c in doc["counties"].values():
        for chamber in CHAMBERS.values():
            for r in c[chamber]:
                total[(chamber, r["district"])] = total.get((chamber, r["district"]), 0) + r["population"]
    rows = []
    for fips, c in doc["counties"].items():
        for chamber in CHAMBERS.values():
            for r in c[chamber]:
                rows.append([chamber, r["district"], fips, c["name"], r["population"],
                             round(r["population"] / total[(chamber, r["district"])], 5),
                             r["share"], coverage(r["population"], c["population"])])
    chamber_order = {name: i for i, name in enumerate(CHAMBERS.values())}
    rows.sort(key=lambda r: (chamber_order[r[0]], r[1], -r[4], r[2]))
    return rows


def district_counties_csv(doc):
    return _csv(["chamber", "district", "county_fips", "county", "population", "share_of_district",
                 "share_of_county", "coverage"], district_counties_rows(doc))


def tracts_doc(tracts):
    meta = dict(tracts["metadata"])
    meta["schemaVersion"] = SCHEMA_VERSION
    meta["count"] = len(tracts["tracts"])
    return {"metadata": meta, "counties": {fips5(k): v for k, v in tracts["counties"].items()},
            "tracts": tracts["tracts"]}


def tract_districts_csv(tracts):
    rows = []
    for tract_id, rec in sorted(tracts["tracts"].items()):
        for key, chamber in CHAMBERS.items():
            for district, p in sorted(rec[key].items(), key=lambda kv: int(kv[0])):
                rows.append([tract_id, tract_id[:5], chamber, int(district), p, rec["p"]])
    return _csv(["tract_geoid", "county_fips", "chamber", "district", "population", "tract_population"], rows)


# ---- Schemas --------------------------------------------------------------------------

SHARE_LIST = {"type": ["array", "null"], "items": {"type": "object", "properties": {
    "district": {"type": "integer"},
    "share": {"type": "number", "description": "Estimated share of the ZIP's residents, 0-1."}},
    "required": ["district", "share"]},
    "description": "Ranked largest share first. EVERY district with residents is listed."}


def zips_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://raw.githubusercontent.com/{REPO}/main/data/zips.schema.json",
        "title": "Georgia ZIP codes and the districts they touch",
        "description": "Per ZIP, the counties and districts that TOUCH it, never 'your district': a ZIP "
                       "can span several, and only a street address identifies the districts a voter "
                       "lives in. State Senate, state House and U.S. House shares are estimated from "
                       "HUD residential-address ratios and 2020 Census population by 2023 district.",
        "type": "object",
        "required": ["metadata", "zips"],
        "properties": {
            "metadata": {"type": "object"},
            "zips": {"type": "object", "additionalProperties": {
                "type": "object",
                "required": ["kind"],
                "properties": {
                    "city": {"type": ["string", "null"], "description": "Display label from HUD."},
                    "kind": {"enum": ["standard", "po-box", "other"],
                             "description": "standard = a USPS Georgia delivery ZIP; po-box = PO-box-only, "
                                            "carries no districts; other = HUD reports addresses but the "
                                            "ZIP is not in the USPS Georgia facility list (campus, "
                                            "government, military); treat like standard."},
                    "counties": {"type": ["array", "null"], "items": {"type": "object", "properties": {
                        "fips": {"type": "string", "description": "5-digit county FIPS (state 13 + county), e.g. 13089."}, "name": {"type": ["string", "null"]},
                        "share": {"type": "number"}}}},
                    "stateSenate": SHARE_LIST, "stateHouse": SHARE_LIST, "usHouse": SHARE_LIST,
                },
            }},
        },
    }


def _district_rows(chamber_desc):
    return {"type": "array", "description": chamber_desc, "items": {"type": "object", "properties": {
        "district": {"type": "integer"}, "population": {"type": "integer"},
        "share": {"type": ["number", "null"]}}, "required": ["district", "population"]}}


def counties_schema():
    props = {"name": {"type": ["string", "null"]}, "population": {"type": "integer"}}
    for chamber in CHAMBERS.values():
        props[chamber] = _district_rows(f"2020 population of the county in each {chamber} district.")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://raw.githubusercontent.com/{REPO}/main/data/counties.schema.json",
        "title": "Georgia counties and the districts they contain",
        "type": "object",
        "required": ["metadata", "counties"],
        "properties": {
            "metadata": {"type": "object"},
            "counties": {"type": "object", "description": "Keyed by 5-digit county FIPS (state 13 + county), e.g. 13013.",
                         "additionalProperties": {"type": "object", "properties": props,
                                                  "required": ["population"] + list(CHAMBERS.values())}},
        },
    }


def tracts_schema():
    split = {"type": "object", "additionalProperties": {"type": "integer"},
             "description": "district number (zero-padded string) -> tract population in that district"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://raw.githubusercontent.com/{REPO}/main/data/tracts.schema.json",
        "title": "Georgia census tracts and the districts they are split across",
        "type": "object",
        "required": ["metadata", "counties", "tracts"],
        "properties": {
            "metadata": {"type": "object"},
            "counties": {"type": "object", "description": "5-digit county FIPS (state 13 + county) -> name"},
            "tracts": {"type": "object", "description": "Keyed by 11-digit tract GEOID.",
                       "additionalProperties": {"type": "object", "properties": {
                           "p": {"type": "integer", "description": "2020 tract population"},
                           "s": split, "h": split, "c": split},
                           "required": ["p", "s", "h", "c"]}},
        },
    }


# ---- Build + gate ----------------------------------------------------------------------

def build_artifacts():
    zips, tracts = load(ZIPS_SRC), load(TRACTS_SRC)
    if not zips.get("zips"):
        sys.exit("FATAL: ga-zip-districts.json has no ZIPs")
    counties = counties_doc(tracts)
    tracts_pub = tracts_doc(tracts)
    return {
        "data/zips.json": compact_json(zips_doc(zips)),
        "data/zip-districts.csv": zip_districts_csv(zips),
        "data/zip-counties.csv": zip_counties_csv(zips),
        "data/zips.schema.json": build_json(zips_schema()),
        "data/counties.json": build_json(counties),
        "data/county-districts.csv": county_districts_csv(counties),
        "data/district-counties.csv": district_counties_csv(counties),
        "data/counties.schema.json": build_json(counties_schema()),
        "data/tracts.json": compact_json(tracts_pub),
        "data/tract-districts.csv": tract_districts_csv(tracts),
        "data/tracts.schema.json": build_json(tracts_schema()),
    }


def validate(artifacts):
    """Record floors for each dataset, plus the population invariant: the county
    table must add up to the same total as the tract table it came from."""
    min_items("data/zips.json", "zips", minimum=MIN_ZIPS)(artifacts)
    min_items("data/counties.json", "counties", minimum=MIN_COUNTIES)(artifacts)
    min_items("data/tracts.json", "tracts", minimum=MIN_TRACTS)(artifacts)
    counties = json.loads(artifacts["data/counties.json"])
    total = counties["metadata"]["totalPopulation"]
    got = sum(c["population"] for c in counties["counties"].values())
    if got != total:
        raise ValueError(f"refusing to publish: county populations sum to {got:,}, tract table says {total:,}")
    for fips, c in counties["counties"].items():
        for chamber in CHAMBERS.values():
            s = sum(r["population"] for r in c[chamber])
            if s != c["population"]:
                raise ValueError(f"refusing to publish: county {fips} {chamber} districts sum to "
                                 f"{s:,}, county population is {c['population']:,}")
    rows = list(csv.DictReader(io.StringIO(artifacts["data/district-counties.csv"].decode())))
    if not rows or any(len(r["county_fips"]) != 5 or not r["county_fips"].startswith(GA_STATE_FIPS)
                       for r in rows):
        raise ValueError("refusing to publish: district-counties.csv has no rows or a county_fips "
                         "that is not a 5-digit Georgia code")
    for chamber in CHAMBERS.values():
        share = {}
        for r in rows:
            if r["chamber"] == chamber:
                share[r["district"]] = share.get(r["district"], 0) + float(r["share_of_district"])
        bad = [d for d, v in share.items() if abs(v - 1) > 0.005]
        if bad:
            raise ValueError(f"refusing to publish: {chamber} districts {bad[:5]} do not sum to 1 "
                             f"across their counties")


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV, validate=validate)


if __name__ == "__main__":
    main()
