#!/usr/bin/env python3
"""Build scripts/data/ga-tract-districts.json: for every Georgia census tract, its
2020 population split by 2023 state Senate, state House and congressional district.

This is a ONE-TIME / on-redistricting build, run by hand. Its output is committed
and read by generate_ga_zip_districts.py, so the quarterly job needs none of the
inputs below. Re-run it only when Georgia redraws its maps or the Census vintage
changes.

Inputs (all public; none are committed):
  * the General Assembly Office of Legislative & Congressional Reapportionment's
    block-equivalency files for the Senate-2023, House-2023 and Congress-2023 plans (xlsx:
    columns "Block" = 15-digit census block GEOID, "DistrictID:1");
  * the Census PL 94-171 geographic header for Georgia, gageo2020.pl, whose block
    rows (SUMLEV 750) carry POP100, the block's 2020 population, and whose county
    rows (SUMLEV 050) give county names. Nothing else from the PL files is needed.

Optional reconciliation, which this script runs whenever its inputs are given:
  * the plans' county reports and packets (pdftotext -layout .txt). The table must
    reproduce the packets' district populations and the county reports'
    county x district populations EXACTLY. (The Congress-2023 plan has no packet in
    our files, so its district totals are checked against the sums of its county
    report instead.) The same numbers come from the same
    census blocks, so any difference means a wrong or mismatched input, and the
    script exits 1 without writing.

Usage:
    python scripts/build_ga_tract_district_table.py \\
        --geo gageo2020.pl \\
        --senate-bef senate-2023-block-equivalency.xlsx \\
        --house-bef house-2023-block-equiv.xlsx \\
        --congress-bef congress-2023-block-equiv.xlsx \\
        [--senate-county-report senate-2023-county-report.txt] \\
        [--senate-packet senate-2023-packet-upd.txt] \\
        [--house-county-report house-2023-county-report.txt] \\
        [--house-packet house-2023-packet-upd.txt] \\
        [--congress-county-report congress-2023-county-report.txt]
"""

import argparse
import collections
import datetime
import os
import re
import sys

from lib.atomic_io import write_json_atomic

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "data", "ga-tract-districts.json")

# POP100 sits seven fields from the end of every geographic-header row; the county
# NAME is eleven from the end. Pinned by the row-width check in read_geo().
POP_FROM_END = -7
COUNTY_BASENAME_FROM_END = -11
ROW_WIDTHS = {"750": 97}


def read_geo(path):
    """(block_pop {15-digit GEOID: pop}, counties {3-digit FIPS: name})."""
    pop, counties = {}, {}
    with open(path, encoding="latin-1") as f:
        for line in f:
            row = line.rstrip("\n").split("|")
            level = row[2]
            if level == "750":
                if len(row) != ROW_WIDTHS["750"]:
                    sys.exit(f"geo header: unexpected block row width {len(row)}; "
                             "the field offsets need re-checking")
                pop[row[9]] = int(row[POP_FROM_END])
            elif level == "050":
                counties[row[9][2:]] = re.sub(r" County$", "", row[COUNTY_BASENAME_FROM_END])
    return pop, counties


def read_bef(path):
    import openpyxl  # lazy: only this manual build needs it
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header
    out = {}
    for block, district in rows:
        if block is None:
            continue
        out[str(block).strip()] = str(district).strip().zfill(3)
    return out


def read_county_report(path):
    rep = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(\S.*?)\s+(\d+)\s+([\d,]+)\s+([\d.]+)%\s*$", line.rstrip())
            if m:
                rep[(m.group(1).strip(), m.group(2).zfill(3))] = int(m.group(3).replace(",", ""))
    return rep


def read_packet(path):
    tot = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(\d{3})\s+([\d,]{5,})\s", line)
            if m and m.group(1) not in tot:
                tot[m.group(1)] = int(m.group(2).replace(",", ""))
    return tot


def roll_up(bef, block_pop):
    """tract -> {district: population}, plus the reconciliation tallies."""
    tracts = collections.defaultdict(collections.Counter)
    for block, district in bef.items():
        tracts[block[:11]][district] += block_pop[block]
    return tracts


def reconcile(label, bef, block_pop, counties, county_report, packet):
    """Exit 1 unless the roll-up reproduces the official reports exactly."""
    problems = []
    missing = [b for b in bef if b not in block_pop]
    extra = [b for b in block_pop if b not in bef]
    if missing:
        problems.append(f"{len(missing)} equivalency blocks have no census population")
    if extra:
        problems.append(f"{len(extra)} census blocks are not assigned to a district")
    dist, cd = collections.Counter(), collections.Counter()
    for block, district in bef.items():
        p = block_pop.get(block, 0)
        dist[district] += p
        cd[(counties[block[2:5]], district)] += p
    if county_report and not packet:
        # No packet for this plan: the report's own district sums stand in for it.
        packet = collections.Counter()
        for (_, d), v in county_report.items():
            packet[d] += v
    if packet:
        bad = {d: (dist.get(d), v) for d, v in packet.items() if dist.get(d) != v}
        if bad:
            problems.append(f"{len(bad)} district totals differ from the packet, e.g. {list(bad.items())[:3]}")
    if county_report:
        bad = {k: (cd.get(k), v) for k, v in county_report.items() if cd.get(k) != v}
        if bad:
            problems.append(f"{len(bad)} county x district rows differ from the county report, "
                            f"e.g. {list(bad.items())[:3]}")
        absent = {k for k, v in cd.items() if v > 0} - set(county_report)
        if absent:
            problems.append(f"{len(absent)} populated county x district pairs are absent from the report")
    if problems:
        sys.exit(f"{label}: does not reconcile with the official reports:\n  " + "\n  ".join(problems))
    print(f"{label}: reconciles ({len(packet or {})} district totals, "
          f"{len(county_report or {})} county rows checked)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geo", required=True)
    ap.add_argument("--senate-bef", required=True)
    ap.add_argument("--house-bef", required=True)
    ap.add_argument("--congress-bef", required=True)
    for name in ("senate-county-report", "senate-packet", "house-county-report", "house-packet",
                 "congress-county-report"):
        ap.add_argument("--" + name)
    args = ap.parse_args()

    block_pop, counties = read_geo(args.geo)
    total = sum(block_pop.values())

    chambers = {}
    for key, label, bef_path, cr_path, pk_path in (
        ("s", "Senate-2023", args.senate_bef, args.senate_county_report, args.senate_packet),
        ("h", "House-2023", args.house_bef, args.house_county_report, args.house_packet),
        ("c", "Congress-2023", args.congress_bef, args.congress_county_report, None),
    ):
        bef = read_bef(bef_path)
        reconcile(label, bef, block_pop, counties,
                  read_county_report(cr_path) if cr_path else None,
                  read_packet(pk_path) if pk_path else None)
        chambers[key] = roll_up(bef, block_pop)

    tract_ids = sorted(set(chambers["s"]) | set(chambers["h"]))
    tracts = {}
    for t in tract_ids:
        rec = {"p": sum(chambers["s"][t].values())}
        for key in ("s", "h", "c"):
            rec[key] = {d: p for d, p in sorted(chambers[key][t].items()) if p > 0}
            if sum(chambers[key][t].values()) != rec["p"]:
                sys.exit(f"tract {t}: the {key} plan's population disagrees with the others")
        tracts[t] = rec

    out = {
        "metadata": {
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "censusVintage": "2020 Census PL 94-171 (block population, POP100)",
            "plans": {"s": "Senate-2023", "h": "House-2023", "c": "Congress-2023"},
            "source": "Georgia General Assembly Office of Legislative & Congressional Reapportionment "
                      "block-equivalency files, joined to U.S. Census Bureau 2020 block populations",
            "tractCount": len(tracts),
            "totalPopulation": total,
            "note": "tracts.<id>.p is the tract's 2020 population; .s, .h and .c map district -> the tract "
                    "population living in that district (Senate, House, Congress). Districts with no population are omitted.",
        },
        "counties": dict(sorted(counties.items())),
        "tracts": tracts,
    }
    write_json_atomic(OUT, out, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(tracts)} tracts, population {total:,}")


if __name__ == "__main__":
    main()
