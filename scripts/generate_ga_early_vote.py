#!/usr/bin/env python3
"""Aggregate Georgia SoS absentee/early-vote files into a county-level JSON.

The SoS files are VOTER-LEVEL (names, addresses). Nothing from them is written out:
the only output is per-county counts and daily totals in _data/early_vote/<election>.json.
Never commit the raw files.

Inputs (manual downloads, since the SoS site is behind a bot challenge):
  --absentee  folder of per-county CSVs of the CURRENT election's absentee/early file
              (the same layout as the past-year dumps: dates, ballot status, reasons).
              STATEWIDE.csv repeats every county and is skipped.
  --registration  SoS active/inactive voter table (.xlsx or .csv: County, Totals, Active, Inactive)
  --prior     YEAR=DIR:ELECTION_DATE  folder of per-county CSVs from a past election
              (e.g. 2022=~/Downloads/A-12054:2022-11-08). May be repeated.
  --prior-active  YEAR=N  statewide active voters on that election day (SoS turnout dashboard).

The as-of date is the latest day with an accepted in-person ballot in the file (mail return
dates include a few stray ones). --as-of overrides it.

Comparison rule: a past year is cut at the SAME number of days before its election day
as the current data is (as-of date vs. election date), counting only accepted ballots
(Ballot Status 'A') by Ballot Return Date. Comparing a partial count to a final one
would make the current year look far behind.

Usage:
  python scripts/generate_ga_early_vote.py --absentee ~/Downloads/A-12601 \
      --registration reg.xlsx --election-date 2026-11-03 \
      --prior 2022=A-12054:2022-11-08 --prior 2024=A-12311:2024-11-05 \
      --prior-active 2022=6961501 --prior-active 2024=7267985
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

IN_PERSON = "EARLY IN-PERSON"
BIG_FOUR = ("Fulton", "DeKalb", "Cobb", "Gwinnett")  # display names; the four largest early-vote counties
DISPLAY_FIXES = {"DEKALB": "DeKalb", "MCDUFFIE": "McDuffie", "MCINTOSH": "McIntosh"}
DAILY_WINDOW = 45  # days before election day kept in the daily series

# Where a mail/electronic ballot stands. A voter can have several records (a ballot cancelled and
# re-issued, a mailed ballot surrendered to vote in person); the one furthest along wins.
PIPELINE_ORDER = ["accepted", "rejected", "outstanding", "other", "cancelled"]  # best first
STATUS_GROUP = {
    "A": "accepted",
    "R": "rejected",
    "I": "outstanding",   # issued, not yet returned
    "C": "cancelled",
    "S": "cancelled",     # spoiled
}


def key(name):
    """County join key: the SoS files disagree on spacing (BENHILL vs BEN HILL)."""
    return "".join(ch for ch in name.upper() if ch.isalpha())


def display(name):
    n = name.strip().upper()
    return DISPLAY_FIXES.get(n, n.title())


def parse_date(s):
    """MM/DD/YYYY, optionally followed by a time."""
    return dt.datetime.strptime(s.strip().split()[0], "%m/%d/%Y").date()


def _csv_paths(directory, label):
    paths = [p for p in sorted(glob.glob(os.path.join(directory, "*.csv")))
             if not os.path.basename(p).upper().startswith("STATEWIDE")]
    if not paths:
        # A wrong or emptied folder must not publish as "0 ballots".
        sys.exit(f"no CSV files in {label} directory: {directory}")
    return paths


def _days_before(ret, election):
    """Days before election day for the daily series. Anything earlier than the window is folded into
    its first day, so the series always adds up to the headline total; after election day is dropped."""
    d = (election - ret).days
    return min(d, DAILY_WINDOW) if d >= 0 else None


def read_current(directory, election, as_of=None):
    """Current-election absentee/early folder.

    -> dict with:
       as_of        the day the file runs through (given, or the latest accepted in-person day)
       counties     {countyKey: {inPerson, mail, pipeline{...}}}; pipeline = mail/electronic ballot RECORDS by status
       daily        {daysBefore: [inPerson, mail]}  accepted ballots by return date, up to as_of
       voters       {voterId: countyKey}  accepted voters (in memory only, for the repeat-voter match)
    """
    best = {}  # voterId -> (rank, countyKey, isInPerson, group, returnDate or None)
    rank = {g: i for i, g in enumerate(PIPELINE_ORDER)}
    # The mail pipeline counts BALLOT RECORDS, not voters (as the SoS dashboard does): a cancelled
    # ballot that was re-issued is one cancelled and one outstanding. Accepted ones wait for as_of.
    records = {}       # countyKey -> {group: n}, every non-accepted mail/electronic record
    accepted_mail = []  # (countyKey, returnDate or None) of accepted mail/electronic records
    for path in _csv_paths(directory, "current"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                inp = row["Ballot Style"].strip().upper() == IN_PERSON
                group = STATUS_GROUP.get(row["Ballot Status"].strip().upper(), "other")
                ret = None
                raw = row["Ballot Return Date"].strip()
                if raw:
                    try:
                        ret = parse_date(raw)
                    except ValueError:
                        ret = None
                rec = (rank[group], key(row["County"]), inp, group, ret)
                if not inp:
                    if group == "accepted":
                        accepted_mail.append((rec[1], ret))
                    else:
                        r = records.setdefault(rec[1], {g: 0 for g in PIPELINE_ORDER})
                        r[group] += 1
                vid = row["Voter Registration #"]
                cur = best.get(vid)
                if cur is None or rec[0] < cur[0]:
                    best[vid] = rec

    if as_of is None:
        days = [r[4] for r in best.values() if r[3] == "accepted" and r[2] and r[4] and r[4] <= election]
        if not days:
            sys.exit("cannot work out the as-of date: no accepted in-person ballots with a return date")
        as_of = max(days)

    counties = {}
    daily = {}
    voters = {}
    for vid, (_, k, inp, group, ret) in best.items():
        c = counties.setdefault(k, {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}})
        if inp:
            # in-person early voting only ever produces accepted ballots; anything else is a stray record
            if group == "accepted" and ret and ret <= as_of:
                c["inPerson"] += 1
                voters[vid] = k
                d = _days_before(ret, election)
                if d is not None:
                    daily.setdefault(d, [0, 0])[0] += 1
            continue
        if group == "accepted":
            if not ret or ret > as_of:
                continue  # a stray return date: not a counted ballot
            c["mail"] += 1
            voters[vid] = k
            d = _days_before(ret, election)
            if d is not None:
                daily.setdefault(d, [0, 0])[1] += 1
    for k, r in records.items():
        c = counties.setdefault(k, {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}})
        for g, n in r.items():
            c["pipeline"][g] += n
    for k, ret in accepted_mail:
        if ret and ret <= as_of:  # a stray return date (the file has a few years out) is not a counted ballot
            c = counties.setdefault(k, {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}})
            c["pipeline"]["accepted"] += 1
    return {"as_of": as_of, "counties": counties, "daily": daily, "voters": voters}


def count_prior(directory, cutoff, election=None):
    """Accepted ballots returned on or before `cutoff`, per county, deduped by voter id.

    -> (totals {countyKey: n}, mail {countyKey: n of absentee/electronic},
        voted {voterId, ...}, daily {daysBefore: [inPerson, mail]})
    `voted` is every voter with an accepted ballot in that election REGARDLESS of date, for the
    repeat-voter match ("voted early or absentee in 2024"); it never leaves memory.
    `daily` covers the whole early period up to election day, not just up to the cutoff, so the
    chart can draw the full past curve. STATEWIDE.csv in these dumps repeats every county row,
    so it is skipped.
    """
    seen = set()
    voted = set()
    out = {}
    mail = {}
    daily = {}
    for path in _csv_paths(directory, "prior-year"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("Ballot Status", "").strip().upper() != "A":
                    continue
                ret = row.get("Ballot Return Date", "").strip()
                if not ret:
                    continue
                vid = row["Voter Registration #"]
                voted.add(vid)
                try:
                    rd = parse_date(ret)
                except ValueError:
                    continue
                if vid in seen:
                    continue
                inp = row.get("Ballot Style", "").strip().upper() == IN_PERSON
                if election is not None:
                    d = _days_before(rd, election)
                    if d is not None:
                        daily.setdefault(d, [0, 0])[0 if inp else 1] += 1
                if rd > cutoff:
                    continue
                seen.add(vid)
                k = key(row["County"])
                out[k] = out.get(k, 0) + 1
                if not inp:
                    mail[k] = mail.get(k, 0) + 1
    return out, mail, voted, daily


def match_repeat(voter_county, voted):
    """{countyKey: how many current voters are also in `voted`} (aggregate only)."""
    matched = {}
    for vid, k in voter_county.items():
        if vid in voted:
            matched[k] = matched.get(k, 0) + 1
    return matched


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


def build(current, registration, priors, priors_mail=None, repeat=None):
    """`current` is read_current()'s `counties`; priors/priors_mail/repeat are {year: {countyKey: n}}."""
    empty = {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}}
    counties = []
    for k, reg in sorted(registration.items(), key=lambda kv: kv[1]["name"]):
        cur = current.get(k, empty)
        total = cur["inPerson"] + cur["mail"]
        rec = {
            "name": display(reg["name"]),
            "ballots": total,
            "inPerson": cur["inPerson"],
            "mail": cur["mail"],
            "active": reg["active"],
            "turnoutPct": round(100.0 * total / reg["active"], 1) if reg["active"] else None,
            "mailPct": round(100.0 * cur["mail"] / total, 1) if total else None,
            "mailPipeline": dict(cur["pipeline"]),
            "prior": {str(y): counts.get(k, 0) for y, counts in priors.items()},
        }
        if priors_mail:
            rec["priorMailPct"] = {
                str(y): round(100.0 * priors_mail[y].get(k, 0) / counts[k], 1) if counts.get(k) else None
                for y, counts in priors.items()
            }
        if repeat:
            # share of this county's 2026 ballots cast by someone who also voted early/absentee in that year
            rec["repeatPct"] = {
                str(y): round(100.0 * r.get(k, 0) / total, 1) if total else None
                for y, r in repeat.items()
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


def daily_series(daily):
    """{daysBefore: [ip, mail]} -> [[daysBefore, ip, mail], ...] from the earliest day to election day."""
    return [[d, daily[d][0], daily[d][1]] for d in sorted(daily, reverse=True)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--absentee", required=True, help="folder of per-county CSVs, current election")
    ap.add_argument("--registration", required=True)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD the file runs through (default: derived)")
    ap.add_argument("--election-date", required=True)
    ap.add_argument("--prior", action="append", default=[], help="YEAR=DIR:ELECTION_DATE")
    ap.add_argument("--prior-active", action="append", default=[],
                    help="YEAR=N statewide active voters on that election day (SoS turnout dashboard)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)

    election = dt.date.fromisoformat(a.election_date)
    cur = read_current(os.path.expanduser(a.absentee), election,
                       dt.date.fromisoformat(a.as_of) if a.as_of else None)
    as_of = cur["as_of"]
    days_before = (election - as_of).days
    registration = read_registration(a.registration)

    priors, priors_mail, repeat, prior_meta, prior_daily = {}, {}, {}, {}, {}
    for spec in a.prior:
        year, rest = spec.split("=", 1)
        directory, edate = rest.rsplit(":", 1)
        pe = dt.date.fromisoformat(edate)
        cutoff = pe - dt.timedelta(days=days_before)
        totals, mail, voted, daily = count_prior(os.path.expanduser(directory), cutoff, pe)
        priors[year], priors_mail[year], prior_daily[year] = totals, mail, daily
        repeat[year] = match_repeat(cur["voters"], voted)
        del voted  # millions of voter ids: drop as soon as the match is done
        prior_meta[year] = {"electionDate": edate, "cutoff": cutoff.isoformat()}

    for spec in a.prior_active:
        year, n = spec.split("=", 1)
        if year not in prior_meta:
            sys.exit(f"--prior-active {year}: no matching --prior")
        prior_meta[year]["activeStatewide"] = int(n)

    counties = build(cur["counties"], registration, priors, priors_mail, repeat)
    errs = validate(counties, cur["counties"], registration)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        sys.exit(1)

    ballots = sum(c["ballots"] for c in counties)
    active = sum(c["active"] for c in counties)
    metro = [c for c in counties if c["name"] in BIG_FOUR]
    metro_keys = {key(n) for n in BIG_FOUR}

    def metro_part(by_county):  # share of a {countyKey: n} tally that sits in the big four
        t = sum(by_county.values())
        return round(100.0 * sum(n for k, n in by_county.items() if k in metro_keys) / t, 1) if t else None

    metro_share = {
        "counties": [c["name"] for c in metro],
        # the same share split by how the ballot was cast
        "inPersonPct": round(100.0 * sum(c["inPerson"] for c in metro) / sum(c["inPerson"] for c in counties), 1),
        "mailPct": round(100.0 * sum(c["mail"] for c in metro) / sum(c["mail"] for c in counties), 1),
        "priorInPersonPct": {
            y: metro_part({k: n - priors_mail[y].get(k, 0) for k, n in priors[y].items()}) for y in priors
        },
        "priorMailPct": {y: metro_part(priors_mail[y]) for y in priors},
        "pct": round(100.0 * sum(c["ballots"] for c in metro) / ballots, 1) if ballots else None,
        "prior": {
            y: round(100.0 * sum(c["prior"][y] for c in metro) / t, 1)
            for y in priors if (t := sum(c["prior"][y] for c in counties))
        },
    }
    pipeline = {g: sum(c["mailPipeline"][g] for c in counties) for g in PIPELINE_ORDER}
    pipeline["total"] = sum(pipeline.values())

    election_year = str(election.year)
    daily = {election_year: daily_series(cur["daily"])}
    daily.update({y: daily_series(d) for y, d in prior_daily.items()})

    data = {
        "metadata": {
            "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "Georgia Secretary of State absentee ballot file and active voter registration table",
            "electionDate": a.election_date,
            "asOf": as_of.isoformat(),
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
            "mailPct": round(100.0 * sum(c["mail"] for c in counties) / ballots, 1) if ballots else None,
            "priorMailPct": {
                y: round(100.0 * sum(priors_mail[y].values()) / sum(priors[y].values()), 1)
                for y in priors if sum(priors[y].values())
            },
            # counts at the same point, by how the ballot was cast (mail = absentee by mail + electronic delivery)
            "priorMail": {y: sum(priors_mail[y].values()) for y in priors},
            "priorInPerson": {y: sum(priors[y].values()) - sum(priors_mail[y].values()) for y in priors},
            "repeatPct": {
                y: round(100.0 * sum(repeat[y].values()) / ballots, 1) for y in repeat
            } if ballots else {},
            "metro": metro_share,
            "mailPipeline": pipeline,
            "prior": {y: sum(c["prior"][y] for c in counties) for y in priors},
            "priorPct": {
                y: round(100.0 * sum(c["prior"][y] for c in counties) / m["activeStatewide"], 1)
                for y, m in prior_meta.items() if m.get("activeStatewide")
            },
        },
        "daily": daily,
        "counties": counties,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    write_json_atomic(a.out, data)
    print(f"wrote {a.out}: {len(counties)} counties, {ballots:,} ballots through {as_of}, "
          f"{data['statewide']['turnoutPct']}% of active")


if __name__ == "__main__":
    main()
