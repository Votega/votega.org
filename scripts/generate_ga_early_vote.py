#!/usr/bin/env python3
"""Aggregate Georgia SoS absentee/early-vote files into a county-level JSON.

The SoS files are VOTER-LEVEL (names, addresses). Nothing from them is written out:
the only output is per-county counts in _data/early_vote/<election>.json. Never commit
the raw files.

Inputs (manual downloads, since the SoS site is behind a bot challenge):
  --current   current-election absentee/early CSV (one row per voter who has voted;
              columns include 'County Name', 'Voter Registration Number', 'Ballot Style')
  --registration  SoS active/inactive voter table (.xlsx or .csv: County, Totals, Active, Inactive)
  --prior     YEAR=DIR:ELECTION_DATE  directory of per-county CSVs from a past election
              (e.g. 2022=~/Downloads/A-12054:2022-11-08). May be repeated.

Comparison rule: a past year is cut at the SAME number of days before its election day
as the current data is (as-of date vs. election date), counting only accepted ballots
(Ballot Status 'A') by Ballot Return Date. Comparing a partial count to a final one
would make the current year look far behind.

Usage:
  python scripts/generate_ga_early_vote.py --current A-12601.csv --registration reg.xlsx \
      --as-of 2026-10-21 --election-date 2026-11-03 \
      --prior 2022=A-12054:2022-11-08 --prior 2024=A-13000:2024-11-05
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_data", "early_vote", "ga-general-2026.json")

# Ballot Style values from the SoS file -> short key used in the output.
STYLES = {
    "EARLY IN-PERSON": "inPerson",
    "ABSENTEE BY MAIL": "mail",
    "ELECTRONIC BALLOT DELIVERY": "electronic",
}
DISPLAY_FIXES = {"DEKALB": "DeKalb", "MCDUFFIE": "McDuffie", "MCINTOSH": "McIntosh"}


def key(name):
    """County join key: the SoS files disagree on spacing (BENHILL vs BEN HILL)."""
    return "".join(ch for ch in name.upper() if ch.isalpha())


def display(name):
    n = name.strip().upper()
    return DISPLAY_FIXES.get(n, n.title())


def parse_date(s):
    return dt.datetime.strptime(s.strip(), "%m/%d/%Y").date()


def count_current(path):
    """-> {countyKey: {'name', 'total', 'inPerson', 'mail', 'electronic'}} (deduped by voter id)."""
    seen = set()
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            vid = row["Voter Registration Number"]
            if vid in seen:
                continue
            seen.add(vid)
            k = key(row["County Name"])
            c = out.setdefault(k, {"total": 0, "inPerson": 0, "mail": 0, "electronic": 0})
            c["total"] += 1
            style = STYLES.get(row["Ballot Style"].strip().upper())
            if style:
                c[style] += 1
    return out


def count_prior(directory, cutoff):
    """Accepted ballots returned on or before `cutoff`, per county, deduped by voter id.

    STATEWIDE.csv in these dumps repeats every county row, so it is skipped.
    """
    seen = set()
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.csv"))):
        if os.path.basename(path).upper().startswith("STATEWIDE"):
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("Ballot Status", "").strip().upper() != "A":
                    continue
                ret = row.get("Ballot Return Date", "").strip()
                if not ret:
                    continue
                try:
                    if parse_date(ret) > cutoff:
                        continue
                except ValueError:
                    continue
                vid = row["Voter Registration #"]
                if vid in seen:
                    continue
                seen.add(vid)
                k = key(row["County"])
                out[k] = out.get(k, 0) + 1
    return out


def read_registration(path):
    """-> {countyKey: {'name', 'active', 'total'}}, statewide row excluded."""
    if path.lower().endswith(".xlsx"):
        import openpyxl  # lazy: only the manual run needs it
        rows = list(openpyxl.load_workbook(path, data_only=True).active.iter_rows(values_only=True))
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    out = {}
    for r in rows:
        if not r or r[0] is None or str(r[0]).strip().upper() in ("", "COUNTY", "TOTALS", "VOTER STATUS"):
            continue
        try:
            total, active = int(r[1]), int(r[2])
        except (TypeError, ValueError):
            continue
        out[key(str(r[0]))] = {"name": str(r[0]).strip(), "active": active, "total": total}
    return out


def build(current, registration, priors, as_of, election_date):
    """priors: {year: {countyKey: n}} plus meta in `priors_meta` is added by caller."""
    counties = []
    for k, reg in sorted(registration.items(), key=lambda kv: kv[1]["name"]):
        cur = current.get(k, {"total": 0, "inPerson": 0, "mail": 0, "electronic": 0})
        rec = {
            "name": display(reg["name"]),
            "ballots": cur["total"],
            "inPerson": cur["inPerson"],
            "mail": cur["mail"] + cur["electronic"],
            "active": reg["active"],
            "turnoutPct": round(100.0 * cur["total"] / reg["active"], 1) if reg["active"] else None,
            "prior": {str(y): counts.get(k, 0) for y, counts in priors.items()},
        }
        counties.append(rec)
    return counties


def validate(counties, current, registration):
    """Tier-1 checks: the output must not contradict its own inputs."""
    errs = []
    if len(counties) != 159:
        errs.append(f"expected 159 counties, got {len(counties)}")
    unmatched = set(current) - set(registration)
    if unmatched:
        errs.append(f"counties in votes but not in registration: {sorted(unmatched)}")
    for c in counties:
        if c["ballots"] > c["active"]:
            errs.append(f"{c['name']}: ballots {c['ballots']} exceed active voters {c['active']}")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--registration", required=True)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD the current file reflects")
    ap.add_argument("--election-date", required=True)
    ap.add_argument("--prior", action="append", default=[], help="YEAR=DIR:ELECTION_DATE")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)

    as_of = dt.date.fromisoformat(a.as_of)
    election = dt.date.fromisoformat(a.election_date)
    days_before = (election - as_of).days

    current = count_current(a.current)
    registration = read_registration(a.registration)
    priors, prior_meta = {}, {}
    for spec in a.prior:
        year, rest = spec.split("=", 1)
        directory, edate = rest.rsplit(":", 1)
        pe = dt.date.fromisoformat(edate)
        cutoff = pe - dt.timedelta(days=days_before)
        priors[year] = count_prior(os.path.expanduser(directory), cutoff)
        prior_meta[year] = {"electionDate": edate, "cutoff": cutoff.isoformat()}

    counties = build(current, registration, priors, as_of, election)
    errs = validate(counties, current, registration)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        sys.exit(1)

    ballots = sum(c["ballots"] for c in counties)
    active = sum(c["active"] for c in counties)
    data = {
        "metadata": {
            "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "Georgia Secretary of State absentee ballot file and active voter registration table",
            "electionDate": a.election_date,
            "asOf": a.as_of,
            "daysBeforeElection": days_before,
            "count": len(counties),
            "comparisons": prior_meta,
        },
        "statewide": {
            "ballots": ballots,
            "inPerson": sum(c["inPerson"] for c in counties),
            "mail": sum(c["mail"] for c in counties),
            "active": active,
            "turnoutPct": round(100.0 * ballots / active, 1) if active else None,
            "prior": {y: sum(c["prior"][y] for c in counties) for y in priors},
        },
        "counties": counties,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    write_json_atomic(a.out, data)
    print(f"wrote {a.out}: {len(counties)} counties, {ballots:,} ballots, {data['statewide']['turnoutPct']}% of active")


if __name__ == "__main__":
    main()
