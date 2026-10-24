#!/usr/bin/env python3
"""Reduce the early-vote page's manual downloads to small files that can live in the repo.

The Secretary of State's downloads are large (the 2024 results export alone is 33 MB) and the site is behind
a bot challenge, so a refresh used to mean re-finding them. Only the aggregates the page reads are kept here;
the VOTER-LEVEL files (absentee and voter history: names, addresses) are never committed.

  results       full SoS results export -> scripts/data/early-vote/results-<year>.json
                (the top-of-ticket race's county totals by voting method, plus the county winner)
  registration  the SoS active/inactive voter table (.xlsx) -> scripts/data/early-vote/registration-<date>.csv

generate_ga_early_vote.py takes the distilled results anywhere it takes the raw export (--prior-json) and the
CSV anywhere it takes the xlsx (--registration). See scripts/data/early-vote/README.md for the refresh.

Usage:
  python scripts/distill_early_vote_inputs.py results ~/Downloads/export-2024NovGen.json --year 2024 --election-date 2024-11-05
  python scripts/distill_early_vote_inputs.py registration ~/Downloads/activeInactiveTable_excel-....xlsx --date 2026-10-23
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_early_vote as g  # noqa: E402
from lib.atomic_io import atomic_write, write_json_atomic  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "early-vote")


def cmd_results(a):
    doc = g.distill_results(os.path.expanduser(a.path), a.election_date)
    out = a.out or os.path.join(OUT_DIR, f"results-{a.year}.json")
    write_json_atomic(out, doc, indent=1)
    won = {}
    for c in doc["counties"].values():
        won[c["winner"]["party"]] = won.get(c["winner"]["party"], 0) + 1
    print(f"wrote {out}: {len(doc['counties'])} counties, {doc['contest']}, carried {won}")


def cmd_registration(a):
    reg = g.read_registration(os.path.expanduser(a.path))
    if len(reg) != 159:
        sys.exit(f"{a.path}: {len(reg)} counties, expected 159")
    out = a.out or os.path.join(OUT_DIR, f"registration-{a.date}.csv")
    with atomic_write(out, newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["County", "Total", "Active"])
        for r in sorted(reg.values(), key=lambda r: r["name"]):
            w.writerow([r["name"], r["total"], r["active"]])
    print(f"wrote {out}: {len(reg)} counties, {sum(r['active'] for r in reg.values()):,} active voters")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("results")
    r.add_argument("path")
    r.add_argument("--year", required=True)
    r.add_argument("--election-date", required=True)
    r.add_argument("--out")
    r.set_defaults(fn=cmd_results)
    g_ = sub.add_parser("registration")
    g_.add_argument("path")
    g_.add_argument("--date", required=True, help="YYYY-MM-DD the table was downloaded")
    g_.add_argument("--out")
    g_.set_defaults(fn=cmd_registration)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
