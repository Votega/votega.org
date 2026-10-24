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
  --prior-history YEAR=CSV  SoS voter history file for a past election (who voted early/by mail, no dates).
              Supplies the repeat-voter figure for a year whose absentee file is incomplete (2022: Fulton and
              Gwinnett are short, and the SoS has no other download); checked against --prior-json.

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
KNOWN_STATUSES = {"A", "R", "I", "C", "S", "PROV", ""}  # anything else is reported, not silently bucketed
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
       quality      what the cleaning dropped (rows, badDates, strayAccepted, duplicateRecords, unknownStatuses)
    """
    best = {}  # voterId -> (rank, countyKey, isInPerson, group, returnDate or None)
    rank = {g: i for i, g in enumerate(PIPELINE_ORDER)}
    # The mail pipeline counts BALLOT RECORDS, not voters (as the SoS dashboard does): a cancelled
    # ballot that was re-issued is one cancelled and one outstanding. Accepted ones wait for as_of.
    records = {}       # countyKey -> {group: n}, every non-accepted mail/electronic record
    accepted_mail = []  # (countyKey, returnDate or None) of accepted mail/electronic records
    q = {"rows": 0, "badDates": 0, "unknownStatuses": {}}  # what the cleaning dropped or could not read
    for path in _csv_paths(directory, "current"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                q["rows"] += 1
                inp = row["Ballot Style"].strip().upper() == IN_PERSON
                status = row["Ballot Status"].strip().upper()
                if status not in KNOWN_STATUSES:
                    q["unknownStatuses"][status] = q["unknownStatuses"].get(status, 0) + 1
                group = STATUS_GROUP.get(status, "other")
                ret = None
                raw = row["Ballot Return Date"].strip()
                if raw:
                    try:
                        ret = parse_date(raw)
                    except ValueError:
                        q["badDates"] += 1
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
    county_daily = {}  # countyKey -> {daysBefore: [inPerson, mail]}, to count 2026 at an earlier comparison point
    voters = {}
    q["duplicateRecords"] = q["rows"] - len(best)  # extra rows for voters already seen (a cancelled and a re-issued ballot, say)
    q["strayAccepted"] = 0     # accepted ballots with no usable return date, or one after the as-of date
    for vid, (_, k, inp, group, ret) in best.items():
        if group == "accepted" and (not ret or ret > as_of):
            q["strayAccepted"] += 1
        c = counties.setdefault(k, {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}})
        if inp:
            # in-person early voting only ever produces accepted ballots; anything else is a stray record
            if group == "accepted" and ret and ret <= as_of:
                c["inPerson"] += 1
                voters[vid] = k
                d = _days_before(ret, election)
                if d is not None:
                    daily.setdefault(d, [0, 0])[0] += 1
                    county_daily.setdefault(k, {}).setdefault(d, [0, 0])[0] += 1
            continue
        if group == "accepted":
            if not ret or ret > as_of:
                continue  # a stray return date: not a counted ballot
            c["mail"] += 1
            voters[vid] = k
            d = _days_before(ret, election)
            if d is not None:
                daily.setdefault(d, [0, 0])[1] += 1
                county_daily.setdefault(k, {}).setdefault(d, [0, 0])[1] += 1
    for k, r in records.items():
        c = counties.setdefault(k, {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}})
        for g, n in r.items():
            c["pipeline"][g] += n
    for k, ret in accepted_mail:
        if ret and ret <= as_of:  # a stray return date (the file has a few years out) is not a counted ballot
            c = counties.setdefault(k, {"inPerson": 0, "mail": 0, "pipeline": {g: 0 for g in PIPELINE_ORDER}})
            c["pipeline"]["accepted"] += 1
    return {"as_of": as_of, "counties": counties, "daily": daily, "county_daily": county_daily,
            "voters": voters, "quality": q}


def count_prior(directory, cutoff, election=None):
    """Accepted ballots returned on or before `cutoff`, per county, deduped by voter id.

    -> (totals {countyKey: n}, mail {countyKey: n of absentee/electronic},
        voted {voterId, ...}, daily {daysBefore: [inPerson, mail]},
        final {countyKey: n}  every accepted ballot with a return date, whatever the date)
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
    final = {}
    for path in _csv_paths(directory, "prior-year"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("Ballot Status", "").strip().upper() != "A":
                    continue
                ret = row.get("Ballot Return Date", "").strip()
                if not ret:
                    continue
                vid = row["Voter Registration #"]
                k = key(row["County"])
                if vid not in voted:
                    final[k] = final.get(k, 0) + 1
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
                out[k] = out.get(k, 0) + 1
                if not inp:
                    mail[k] = mail.get(k, 0) + 1
    return out, mail, voted, daily, final


TOP_TICKET = ("President", "Governor", "US Senate")  # the contest every voter sees, in order of preference


def _method(group_name):
    """Normalize the SoS results export's voting-method labels, which change by year
    ("Advanced Voting" in 2024, "Advance Voting Votes" in 2022)."""
    n = group_name.lower()
    if "advance" in n:
        return "early"
    if "absentee" in n:
        return "mail"
    if "election day" in n:
        return "eday"
    return "prov"


def read_results_json(path):
    """SoS results export (export-YYYYNovGen.json) -> ({countyKey: {early, mail, eday, prov, total}}, contest).

    Votes by voting method for the top-of-ticket race, final counts. Used to check a past-year absentee
    file against the official results, and for each county's early share of final turnout."""
    with open(path, encoding="utf-8") as f:
        counties = (json.load(f).get("localResults")) or []
    if not counties:
        sys.exit(f"{path}: no county results (localResults) in this export")
    for prefix in TOP_TICKET:
        out = {}
        for c in counties:
            item = next((b for b in c["ballotItems"] if b["name"].startswith(prefix)), None)
            if item is None:
                out = None
                break
            g = {"early": 0, "mail": 0, "eday": 0, "prov": 0}
            for o in item["ballotOptions"]:
                for gr in o.get("groupResults") or []:
                    g[_method(gr["groupName"])] += gr["voteCount"]
            g["total"] = sum(g.values())
            out[key(c["name"].replace(" County", ""))] = g
        if out:
            if len(out) != 159:
                sys.exit(f"{path}: {len(out)} counties for {prefix}, expected 159")
            return out, prefix
    sys.exit(f"{path}: none of {TOP_TICKET} is on every county's ballot")


PARTY_CODE = {"REP": "R", "DEM": "D"}


def read_county_winners(path, contest):
    """SoS results export -> {countyKey: {party, candidate, pct, majority}} for `contest` (the top-of-ticket race).

    `party` is R or D (anyone else is O) for the candidate with the most votes; `pct` is that candidate's
    share of ALL the county's votes in the contest, third parties and write-ins included. `majority` is
    pct > 50: a county where nobody cleared half is not called for a party on the page."""
    with open(path, encoding="utf-8") as f:
        counties = (json.load(f).get("localResults")) or []
    out = {}
    for c in counties:
        item = next((b for b in c["ballotItems"] if b["name"].startswith(contest)), None)
        if item is None or not item["ballotOptions"]:
            continue
        opts = item["ballotOptions"]
        total = sum(o["voteCount"] for o in opts)
        if not total:
            continue
        top = max(opts, key=lambda o: o["voteCount"])
        pct = round(100.0 * top["voteCount"] / total, 1)
        out[key(c["name"].replace(" County", ""))] = {
            "party": PARTY_CODE.get((top.get("politicalParty") or "").upper(), "O"),
            "candidate": top["name"],
            "pct": pct,
            "majority": 100.0 * top["voteCount"] / total > 50.0,
        }
    return out


def match_repeat(voter_county, voted):
    """{countyKey: how many current voters are also in `voted`} (aggregate only)."""
    matched = {}
    for vid, k in voter_county.items():
        if vid in voted:
            matched[k] = matched.get(k, 0) + 1
    return matched


HISTORY_EARLY = {"EARLY IN-PERSON", "ABSENTEE BY MAIL", "ELECTRONIC BALLOT DELIVERY", "EARLY", "ABSENTEE"}


def _vid(raw):
    """A voter id with its leading zeros dropped: the voter history file zero-pads to 8 digits, the absentee files do not."""
    return str(raw).strip().lstrip("0")


def read_history(path):
    """SoS voter history file for a past election (who voted, and how; NO return dates).

    -> (voted {normalized voter id} who cast an early or absentee ballot, counts {countyKey: n of those voters}).
    Used only where that year's absentee file is incomplete, for the repeat-voter match: it has every
    county but cannot rebuild a daily series. `path` is the CSV or a folder holding it.
    """
    paths = sorted(glob.glob(os.path.join(path, "*.csv"))) if os.path.isdir(path) else [path]
    if not paths or not all(os.path.isfile(p) for p in paths):
        sys.exit(f"voter history: no CSV at {path}")
    voted, counts = set(), {}
    for p in paths:
        with open(p, newline="", encoding="utf-8-sig", errors="replace") as f:
            for row in csv.DictReader(f):
                if row["Ballot Style"].strip().upper() not in HISTORY_EARLY:
                    continue
                vid = _vid(row["Voter Registration Number"])
                if vid and vid not in voted:
                    voted.add(vid)
                    k = key(row["County Name"])
                    counts[k] = counts.get(k, 0) + 1
    return voted, counts


def match_repeat_history(voter_county, voted):
    """match_repeat, for a `voted` set of normalized ids (read_history): current ids are normalized the same way."""
    matched = {}
    for vid, k in voter_county.items():
        if _vid(vid) in voted:
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


def build(current, registration, priors, priors_mail=None, repeat=None, at_point=None, early_share=None, lean=None):
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
        if at_point:
            # this year's ballots at each past year's comparison point (it differs from the headline when a past
            # year can only be compared at an earlier day)
            rec["atPoint"] = {str(y): sum(c.get(k, [0, 0])) for y, c in at_point.items()}
        if early_share:
            rec["earlyShare"] = {str(y): c.get(k) for y, c in early_share.items()}
        if lean:
            # who carried the county in each past election's top-of-ticket race (None: no result for the county)
            rec["lean"] = {str(y): c.get(k) for y, c in lean.items()}
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


def check_output(data, prev=None, today=None):
    """Whole-output checks. -> (errors, warnings).

    Errors mean the file contradicts itself or would replace good data with worse data: they stop the
    run and nothing is written. Warnings are things the cleaning dropped or could not explain; they are
    printed loudly and kept in metadata.quality, but do not stop the run.
    """
    errors, warnings = [], []
    md, sw = data["metadata"], data["statewide"]
    election = dt.date.fromisoformat(md["electionDate"])
    as_of = dt.date.fromisoformat(md["asOf"])
    today = today or dt.datetime.now(dt.timezone.utc).date()
    cur_year = str(election.year)

    # the daily series must add up to the headline numbers it is drawn beside
    cur_sum = sum(r[1] + r[2] for r in data["daily"].get(cur_year, []))
    if cur_sum != sw["ballots"]:
        errors.append(f"daily series for {cur_year} adds up to {cur_sum:,} but the headline is {sw['ballots']:,} ballots")
    for y, meta in md["comparisons"].items():
        total = sw["prior"].get(y, 0)
        if total <= 0:
            errors.append(f"{y}: no ballots counted at the same point (wrong or empty folder, or a wrong election date?)")
            continue
        edate = dt.date.fromisoformat(meta["electionDate"])
        cutoff_days = (edate - dt.date.fromisoformat(meta["cutoff"])).days
        s = sum(r[1] + r[2] for r in data["daily"].get(y, []) if r[0] >= cutoff_days)
        if s != total:
            errors.append(f"{y}: daily series up to the cutoff adds up to {s:,} but the same-point total is {total:,}")

    # a comparison made at this year's own latest day must equal the headline
    for y, meta in md["comparisons"].items():
        pt = sw.get("atPoint", {}).get(y)
        if pt and meta.get("daysBefore") == md["daysBeforeElection"] and pt["ballots"] != sw["ballots"]:
            errors.append(f"{y}: this year's ballots at the comparison point ({pt['ballots']:,}) differ from the headline ({sw['ballots']:,})")

    # a past year's absentee file must agree with that election's official results, county by county
    for y, short in md.get("pastYearGaps", {}).items():
        declared = "lastCompleteDate" in md["comparisons"].get(y, {})
        names = ", ".join(f"{g['county']} ({g['file']:,} in the file vs {g['official']:,} official)" for g in short[:6])
        if short and not declared:
            errors.append(f"{y}: the absentee file is more than 3% short of the official early + mail votes in {len(short)} counties: {names}. "
                          f"Get a complete file, or declare the last complete day with --prior-last-good")
        elif short:
            warnings.append(f"{y}: {len(short)} counties are short in the absentee file ({names}); the comparison is cut at "
                            f"{md['comparisons'][y]['lastCompleteDate']}, the last complete day"
                            + ("; the repeat-voter figure comes from the voter history file"
                               if md["comparisons"][y].get("repeatSource") else ", and the repeat-voter figure is omitted"))
        elif declared:
            warnings.append(f"{y}: declared incomplete after {md['comparisons'][y]['lastCompleteDate']}, but no county is more than 3% off the official totals: is the cut still needed?")

    if as_of > election:
        errors.append(f"as-of date {as_of} is after election day {election}")
    if as_of > today + dt.timedelta(days=1):
        errors.append(f"as-of date {as_of} is in the future (today is {today})")

    # never replace a good file with an older or smaller one
    if prev and prev.get("metadata", {}).get("electionDate") == md["electionDate"]:
        pm, ps = prev["metadata"], prev["statewide"]
        if as_of < dt.date.fromisoformat(pm["asOf"]):
            errors.append(f"as-of {as_of} is OLDER than the committed file's {pm['asOf']}: is this an old download?")
        if sw["ballots"] < ps["ballots"] * 0.995:
            errors.append(f"ballots fell from {ps['ballots']:,} to {sw['ballots']:,} (more than 0.5%): a truncated file?")

    pipe_acc, mail = sw["mailPipeline"]["accepted"], sw["mail"]
    if pipe_acc != mail:
        (errors if abs(pipe_acc - mail) > max(1, mail * 0.01) else warnings).append(
            f"mail pipeline says {pipe_acc:,} accepted but the headline has {mail:,} mail ballots")

    # what the cleaning dropped, said out loud
    q = md.get("quality", {})
    if q.get("strayAccepted", 0) > max(5, sw["ballots"] * 0.001):
        errors.append(f"{q['strayAccepted']:,} accepted ballots have no usable return date or one after {as_of}: more than 0.1% of the total")
    elif q.get("strayAccepted"):
        warnings.append(f"{q['strayAccepted']:,} accepted ballots were dropped for a missing or out-of-range return date")
    if q.get("badDates"):
        warnings.append(f"{q['badDates']:,} return dates could not be read")
    if q.get("unknownStatuses"):
        warnings.append(f"unrecognized ballot status codes (counted as 'pending'): {q['unknownStatuses']}")
    if q.get("duplicateRecords"):
        warnings.append(f"{q['duplicateRecords']:,} repeat records for the same voter were merged (best status kept)")
    if (today - as_of).days > 2:
        warnings.append(f"the file runs through {as_of}, {(today - as_of).days} days ago: refresh the download")
    empty = [c["name"] for c in data["counties"] if c["ballots"] == 0]
    if empty:
        warnings.append(f"{len(empty)} counties have zero ballots so far: {', '.join(empty[:6])}")
    return errors, warnings


def emit(errors, warnings):
    """Say it loudly: a banner on stderr, plus GitHub Actions annotations when run in CI."""
    ci = os.environ.get("GITHUB_ACTIONS") == "true"
    if errors:
        bar = "!" * 72
        print(bar, file=sys.stderr)
        print("!!! EARLY VOTE DATA CHECK FAILED. NOTHING WAS WRITTEN. !!!", file=sys.stderr)
        print(bar, file=sys.stderr)
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
            if ci:
                print(f"::error title=Early vote data check::{e}")
        print(bar, file=sys.stderr)
    if warnings:
        print("--- WARNINGS (the run continues; read these) ---", file=sys.stderr)
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)
            if ci:
                print(f"::warning title=Early vote data check::{w}")
        print("---", file=sys.stderr)


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
    ap.add_argument("--prior-last-good", action="append", default=[],
                    help="YEAR=YYYY-MM-DD last day that year's absentee file is complete; later days are not used")
    ap.add_argument("--prior-json", action="append", default=[],
                    help="YEAR=path to that year's SoS results export (export-YYYYNovGen.json): cross-checks the "
                         "absentee file and gives each county's early share of final turnout")
    ap.add_argument("--prior-history", action="append", default=[],
                    help="YEAR=path to that year's SoS voter history CSV (or its folder): gives the repeat-voter "
                         "figure for a year whose absentee file is incomplete (it has no return dates, so no daily series)")
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

    last_good = {}
    for spec in a.prior_last_good:
        year, d = spec.split("=", 1)
        last_good[year] = dt.date.fromisoformat(d)
    results, lean = {}, {}
    for spec in a.prior_json:
        year, path = spec.split("=", 1)
        results[year] = read_results_json(os.path.expanduser(path))
        lean[year] = read_county_winners(os.path.expanduser(path), results[year][1])

    history = {}
    for spec in a.prior_history:
        year, path = spec.split("=", 1)
        history[year] = read_history(os.path.expanduser(path))

    priors, priors_mail, repeat, prior_meta, prior_daily, prior_final = {}, {}, {}, {}, {}, {}
    for spec in a.prior:
        year, rest = spec.split("=", 1)
        directory, edate = rest.rsplit(":", 1)
        pe = dt.date.fromisoformat(edate)
        cutoff = pe - dt.timedelta(days=days_before)
        meta = {"electionDate": edate}
        if year in last_good and last_good[year] < cutoff:
            # this year's file is only complete up to a day before the same-point cutoff: compare there instead
            cutoff = last_good[year]
            meta["lastCompleteDate"] = cutoff.isoformat()
            meta["lastCompleteDaysBefore"] = (pe - cutoff).days
        meta["cutoff"] = cutoff.isoformat()
        meta["daysBefore"] = (pe - cutoff).days
        totals, mail, voted, daily, final = count_prior(os.path.expanduser(directory), cutoff, pe)
        if "lastCompleteDaysBefore" in meta:  # the series stops where the file stops being complete
            daily = {d: v for d, v in daily.items() if d >= meta["lastCompleteDaysBefore"]}
        priors[year], priors_mail[year], prior_daily[year], prior_final[year] = totals, mail, daily, final
        if year in history:
            # the history file has every county but no dates, so it is held to the official totals the way
            # the absentee file is: a short one would undercount who voted before
            h_voted, h_counts = history[year]
            if year in results:
                short = [k for k, g in results[year][0].items()
                         if (g["early"] + g["mail"]) and abs(h_counts.get(k, 0) - (g["early"] + g["mail"])) / (g["early"] + g["mail"]) > 0.03]
                if short:
                    sys.exit(f"--prior-history {year}: the voter history is more than 3% off the official early + mail votes in "
                             f"{len(short)} counties ({', '.join(display(k) for k in short[:6])}): not a complete file")
            else:
                print(f"WARNING: --prior-history {year} was not checked against official results (no --prior-json {year})", file=sys.stderr)
            repeat[year] = match_repeat_history(cur["voters"], h_voted)
            meta["repeatSource"] = "voter history"
            del h_voted
        elif "lastCompleteDaysBefore" not in meta:
            repeat[year] = match_repeat(cur["voters"], voted)
        # (an incomplete file would undercount who voted before, so no repeat-voter figure for that year unless history supplies it)
        del voted  # millions of voter ids: drop as soon as the match is done
        prior_meta[year] = meta

    # this year's ballots at each past year's comparison point, per county
    at_point = {}
    for year, meta in prior_meta.items():
        dmin = meta["daysBefore"]
        at_point[year] = {k: [sum(v[0] for d, v in days.items() if d >= dmin),
                              sum(v[1] for d, v in days.items() if d >= dmin)]
                          for k, days in cur["county_daily"].items()}
    early_share = {}
    for year, (res, contest) in results.items():
        early_share[year] = {k: round(100.0 * (g["early"] + g["mail"]) / g["total"], 1) if g["total"] else None
                             for k, g in res.items()}

    # past-year absentee file vs the official results: which counties are short?
    past_gaps = {}
    for year, (res, contest) in results.items():
        if year not in prior_final:
            continue
        short = []
        for k, g in res.items():
            official = g["early"] + g["mail"]
            have = prior_final[year].get(k, 0)
            if official and abs(have - official) / official > 0.03:
                short.append({"county": display(k), "file": have, "official": official})
        past_gaps[year] = short

    for spec in a.prior_active:
        year, n = spec.split("=", 1)
        if year not in prior_meta:
            sys.exit(f"--prior-active {year}: no matching --prior")
        prior_meta[year]["activeStatewide"] = int(n)

    counties = build(cur["counties"], registration, priors, priors_mail, repeat, at_point, early_share, lean)
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
            "quality": {k: v for k, v in cur["quality"].items() if k != "rows"},
            "pastYearGaps": past_gaps,
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
            # this year's own ballots at each past year's comparison point (the headline is as of the file's last day)
            "atPoint": {
                y: {"ballots": sum(ip + m for ip, m in pts.values()),
                    "inPerson": sum(ip for ip, m in pts.values()),
                    "mail": sum(m for ip, m in pts.values()),
                    "pct": round(100.0 * sum(ip + m for ip, m in pts.values()) / active, 1) if active else None}
                for y, pts in at_point.items()
            },
            # share of each past election's final votes cast early or by mail (SoS results export)
            "earlyShare": {
                y: {"pct": round(100.0 * sum(g["early"] + g["mail"] for g in res.values())
                                 / sum(g["total"] for g in res.values()), 1),
                    "contest": contest}
                for y, (res, contest) in results.items()
            },
            "priorPct": {
                y: round(100.0 * sum(c["prior"][y] for c in counties) / m["activeStatewide"], 1)
                for y, m in prior_meta.items() if m.get("activeStatewide")
            },
        },
        "daily": daily,
        "counties": counties,
    }
    prev = None
    if os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, ValueError):
            prev = None
    errs, warns = check_output(data, prev)
    emit(errs, warns)
    if errs:
        sys.exit(1)
    data["metadata"]["quality"]["warnings"] = warns
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    write_json_atomic(a.out, data)
    print(f"wrote {a.out}: {len(counties)} counties, {ballots:,} ballots through {as_of}, "
          f"{data['statewide']['turnoutPct']}% of active")


if __name__ == "__main__":
    main()
