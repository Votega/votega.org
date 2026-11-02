#!/usr/bin/env python3
"""Mirror the Georgia millage dataset to the Votega/ga-local-government open-data repo.

    python scripts/publish_ga_millage.py --input "$RUNNER_TEMP/millage"

Phase 1a/1b of docs/LOCAL-EXPANSION-SCOPE.md, decision 1: millage folds into the
EXISTING ga-local-government repo rather than getting one of its own.

WHY A SECOND PUBLISHER RATHER THAN ADDING TO publish_ga_local_government.py
---------------------------------------------------------------------------
That publisher runs from update-local-government.yml TWICE WEEKLY, because a
county can reskin its website at any time. Millage changes once a year, when DOR
posts a new workbook, and rebuilding it means re-downloading ~14MB of
spreadsheets. Bolting it on would do that ~100 times a year for nothing.

Splitting is safe because lib.sibling_publish._publish PUTs each artifact path
through the GitHub Contents API individually — it is an upsert, not a tree
replace — so this publisher touches only the paths it names and leaves the
agenda-mention data alone. For the same reason it must NOT write `latest.json`:
that index belongs to the mentions publisher, which lists these files statically
(their paths are stable regardless of which job ran last).

The shared LICENSE/NOTICE.md are injected by publish_or_dry_run, byte-identical
to the other publisher's, which is the documented intent.
"""

import argparse
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.sibling_publish import (build_json, min_items,  # noqa: E402
                                 publish_or_dry_run)

REPO = "Votega/ga-local-government"
TOKEN_ENV = "GA_LOCAL_GOVERNMENT_TOKEN"
SCHEMA_VERSION = "1.0.0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(ROOT, "assets", "data")
PLACES_JSON = os.path.join(ROOT, "_data", "millage.json")

# One year of the workbook is ~1,725-1,814 rows. The floor is deliberately below
# a single year, so a transform that emits a well-formed but gutted dataset is
# refused while DOR dropping a year is not treated as corruption.
MIN_ROWS = 1500

FIELD_DOC = {
    "taxYear": "Tax year the digest describes.",
    "countyCode": "DOR county code, 1-159 alphabetically. Part of the key.",
    "countyName": ("Canonical county name for that code. DOR abbreviates some "
                   "names per row, giving 191 distinct names for 159 codes, so "
                   "this is the modal name per code and NOT a join key."),
    "countyNameAsFiled": "The county name exactly as that year's workbook wrote it.",
    "districtCode": ("Tax district code within the county. Part of the key. "
                     "Only codes 0-3 mean the same thing statewide "
                     "(countywide/state/school/county incorporated); above that "
                     "they are per-county arbitrary."),
    "districtName": ("District name as filed. DRIFTS BETWEEN YEARS for ~15% of "
                     "districts, in both directions, with no consistent "
                     "transform. Never join on it."),
    "districtType": ("Derived classification: countywide, state, school, "
                     "city_school, county_incorporated, county_unincorporated, "
                     "county_service_district, city, fire, tad, cid, bid, ssd, "
                     "hospital, library, recreation, development_authority."),
    "occurrence": ("1 for every row except where DOR lists the same "
                   "county/district/year twice. Part of the key so repeated rows "
                   "stay distinguishable; they are published unmerged."),
    "millageMO": "Maintenance-and-operations millage rate. null = none reported.",
    "millageBond": "Bond millage rate. null = none reported.",
    "totalTaxMO": "Total M&O tax levied, in dollars.",
    "totalTaxBond": "Total bond tax levied, in dollars.",
    "assessedValueMO": "Net M&O assessed value (40% of fair market value).",
    "assessedValueBond": "Net bond assessed value.",
}

NUMERIC = {"taxYear", "occurrence", "millageMO", "millageBond", "totalTaxMO",
           "totalTaxBond", "assessedValueMO", "assessedValueBond"}


def read_dataset(in_dir):
    path = os.path.join(in_dir, "ga-millage.json")
    if not os.path.exists(path):
        raise SystemExit("ERROR: %s not found. Run scripts/generate_ga_millage.py "
                         "--out %s first." % (path, in_dir))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rows_csv(fields, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(fields)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue().encode("utf-8")


def row_schema(fields):
    props = {}
    for f in fields:
        props[f] = {
            "type": (["number", "null"] if f in NUMERIC else ["string", "null"]),
            "description": FIELD_DOC.get(f, ""),
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Georgia county ad valorem millage rate record",
        "description": ("One tax district in one county in one tax year, from the "
                        "Georgia Department of Revenue's Tax Digest Consolidated "
                        "Summaries. The key is "
                        "(countyCode, districtCode, taxYear, occurrence)."),
        "type": "object",
        "properties": props,
        "required": ["taxYear", "countyCode", "districtCode", "districtType"],
        "additionalProperties": False,
    }


def summary_md(meta, rows, fields):
    years = meta.get("years") or []
    idx = {f: i for i, f in enumerate(fields)}
    counties = len({r[idx["countyCode"]] for r in rows})
    types = {}
    for r in rows:
        t = r[idx["districtType"]]
        types[t] = types.get(t, 0) + 1
    lines = [
        "# Georgia property tax millage rates",
        "",
        "Every taxing jurisdiction's millage rate, tax levied and assessed value,",
        "by county and tax district, for each published tax year.",
        "",
        "| | |",
        "|---|---|",
        "| Rows | %d |" % len(rows),
        "| Tax years | %s |" % (", ".join(str(y) for y in years) or "n/a"),
        "| Counties | %d of 159 |" % counties,
        "| Source | Georgia Department of Revenue, Tax Digest Consolidated Summaries |",
        "| Updated | annually, when DOR publishes a new workbook |",
        "",
        "## Files",
        "",
        "| File | Contents |",
        "|---|---|",
        "| `data/millage.json` | every row, columnar (field names once, rows as arrays) |",
        "| `data/millage.csv` | the same rows as a spreadsheet |",
        "| `data/millage.schema.json` | JSON Schema for one row, with field notes |",
        "| `data/millage-places.json` | the per-place reduction votega.org renders |",
        "",
        "## Reading it correctly",
        "",
        "**The key is `(countyCode, districtCode, taxYear, occurrence)`.** Do not join",
        "on a name. District names drift between years for about 15% of districts, in",
        "both directions and with no consistent transform — a county's school line may",
        "be `SCHOOL` one year and `<County> County - SCHOOL` the next. County names are",
        "worse: DOR abbreviates them per row (`ATKINS`, `BENHIL`, `CHARLT TB`), giving",
        "191 distinct names for 159 codes, so `countyName` here is a canonical label and",
        "`countyNameAsFiled` is what the workbook said.",
        "",
        "**A null rate is not zero.** `null` means the jurisdiction reported no rate;",
        "`0` means it levied zero. Georgia's *state* property tax has been zero",
        "throughout, so every state row that reports a rate reports `0`.",
        "",
        "**Only district codes 0-3 are meaningful statewide** — countywide, state,",
        "county school system, county incorporated. Above that they are per-county",
        "arbitrary: code 15 is `COUNTY UNINCORPORATED` in two dozen counties and a city",
        "elsewhere. Use `districtType`, which is derived from the name for those.",
        "",
        "**A city school system is listed under each county it serves,** so the same",
        "system appears more than once in a year — Atlanta Public Schools under both",
        "Fulton and DeKalb.",
        "",
        "**Known source quirks.** DOR lists Cherokee 2022 district 18 twice with",
        "different assessed values; both rows are published unmerged, distinguished by",
        "`occurrence`. The 2020 workbook is published as `2020-digest-excluding-charlton`.",
        "",
        "## District types",
        "",
        "| Type | Rows |",
        "|---|---|",
    ]
    for t, n in sorted(types.items(), key=lambda kv: -kv[1]):
        lines.append("| `%s` | %d |" % (t, n))
    lines += ["", "Generated by VoteGA.org from public records. See LICENSE and NOTICE.md.", ""]
    return "\n".join(lines).encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_IN,
                    help="directory holding ga-millage.json (generate_ga_millage.py --out)")
    ap.add_argument("--places", default=PLACES_JSON,
                    help="the per-place reduction (build_millage_places.py)")
    args = ap.parse_args()

    blob = read_dataset(args.input)
    meta = blob["metadata"]
    fields = meta["fields"]
    rows = blob["rows"]

    artifacts = {
        "data/millage.json": build_json(blob),
        "data/millage.csv": rows_csv(fields, rows),
        "data/millage.schema.json": build_json(row_schema(fields)),
        "MILLAGE.md": summary_md(meta, rows, fields),
    }
    if os.path.exists(args.places):
        with open(args.places, encoding="utf-8") as fh:
            artifacts["data/millage-places.json"] = build_json(json.load(fh))
    else:
        print("note: %s not found — publishing without the per-place reduction"
              % args.places)

    publish_or_dry_run(REPO, artifacts, TOKEN_ENV,
                       validate=min_items("data/millage.json", "rows",
                                          minimum=MIN_ROWS))


if __name__ == "__main__":
    main()
