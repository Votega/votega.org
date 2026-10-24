#!/usr/bin/env python3
"""Build the early-vote dataset for the Votega/ga-races-elections repo, under early-vote/<year>-general/.

Sources (written by generate_ga_early_vote.py, which is run by hand when the Secretary of State posts a file):
  _data/early_vote/ga-general-2026.json              county totals, mail pipeline, same-point comparisons
  _data/early_vote/ga-general-2026-county-daily.json accepted ballots by county and day (this year + complete past years)
  scripts/data/ga-county-context.json                county FIPS codes (and the Census context the totals carry)
  scripts/data/early-vote/DATA-DICTIONARY.md         what the SoS source files mean

Artifacts (under early-vote/<year>-general/):
  county-totals.json / .csv          one row per county
  county-by-day.json / .csv          one row per county, election year and day before election day
  county-totals.schema.json, county-by-day.schema.json
  README.md, source-data-dictionary.md

Everything published is an aggregate at county level or above. No voter-level field, nothing below county,
no demographics. Counts of 1-9 in the sensitive mail statuses (rejected, cancelled or spoiled, other) are
withheld; accepted ballots are a public record of who voted and are not.

Output is deterministic (no wall-clock time), so an unchanged refresh publishes nothing.
Run standalone to dry-run into ./out; the manual workflow sets OUT_DIR to a target-repo checkout.
"""
import csv
import io
import json
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.sibling_publish import build_json, publish_or_dry_run, min_items  # noqa: E402
import generate_ga_early_vote as gen  # noqa: E402  (key(): the county-name normalizer)

REPO = "Votega/ga-races-elections"
TOKEN_ENV = "GA_RACES_TOKEN"
RAW_BASE = "https://raw.githubusercontent.com/Votega/ga-races-elections/main"
SCHEMA_VERSION = "1.0.0"
SUPPRESS_BELOW = 10  # a count of 1..9 in a sensitive mail status is withheld

SRC_TOTALS = "_data/early_vote/ga-general-2026.json"
SRC_DAILY = "_data/early_vote/ga-general-2026-county-daily.json"
SRC_CONTEXT = "scripts/data/ga-county-context.json"
SRC_DICTIONARY = "scripts/data/early-vote/DATA-DICTIONARY.md"

SENSITIVE = ("mail_rejected", "mail_cancelled_or_spoiled", "mail_other")

STABILITY = {
    "totals": "Stable column names and meanings. Comparison columns are added for each past election the "
              "page compares against (ballots_<year>_same_point and so on), so the set of columns can grow "
              "when a year is added; existing ones keep their meaning. A blank count in mail_rejected, "
              "mail_cancelled_or_spoiled or mail_other means 1 to 9 (withheld), not zero.",
    "byDay": "Stable column names and meanings. days_before 45 holds every accepted ballot 45 or more days "
             "before election day and has no date. Only elections whose Secretary of State file is complete "
             "are included, so 2022 is absent by design.",
}


def schema_url(path):
    return f"{RAW_BASE}/{path}"


def suppress(n):
    """Withhold a small non-zero count in a sensitive status; None for withheld."""
    return None if n is not None and 0 < n < SUPPRESS_BELOW else n


def base_columns(comparison_years, current_year, counties):
    """[(name, json type, description)] for county-totals, in CSV order. as_of is last, by convention."""
    c0 = counties[0]
    cols = [
        ("county_fips", "string", "5-digit county FIPS code (13 + county)."),
        ("county", "string", "County name."),
        ("active_voters", "integer", "Registered voters with active status (Secretary of State active/inactive table). The denominator of turnout_pct_of_active."),
        ("ballots", "integer", "Accepted ballots so far: early in person plus accepted mail and electronic ballots, one per voter."),
        ("in_person", "integer", "Accepted early in-person ballots."),
        ("mail", "integer", "Accepted mail and electronic-delivery ballots."),
        ("turnout_pct_of_active", "number", "ballots as a percentage of active_voters."),
    ]
    if "adultPct" in c0:
        cols += [
            ("citizen_adults_est", "integer", "ESTIMATED citizen adults: residents 18 and over minus non-citizen residents of every age, from the Census Bureau's American Community Survey (newest 5-year vintage), compiled by Georgia Civic Data (CC BY 4.0). Runs slightly low because the source table has no age split."),
            ("ballots_pct_of_citizen_adults_est", "number", "ballots as a percentage of citizen_adults_est."),
            ("adults_25plus_bachelors_pct", "number", "Percent of adults 25 and over with a bachelor's degree or higher (ACS, via Georgia Civic Data)."),
        ]
    cols += [
        ("mail_outstanding", "integer", "Mail and electronic ballots issued but not yet returned."),
        ("mail_rejected", "integer", "Mail ballots rejected after return. Blank = 1 to 9 (withheld)."),
        ("mail_cancelled_or_spoiled", "integer", "Mail ballots cancelled or spoiled. Blank = 1 to 9 (withheld)."),
        ("mail_other", "integer", "Mail records with no ballot yet (for example an application awaiting cure). Blank = 1 to 9 (withheld)."),
    ]
    for y in comparison_years:
        cols += [
            (f"ballots_{y}_same_point", "integer", f"Ballots accepted in {y} at the comparison point for {y} (see metadata.comparisons for how many days before election day)."),
            (f"ballots_{current_year}_at_{y}_point", "integer", f"This year's ballots at that same point, so the two can be compared directly."),
            (f"early_share_{y}_pct", "number", f"Percent of {y}'s final votes in the county's top contest cast early or by mail (certified results)."),
            (f"carried_{y}", "string", f"Party whose candidate won more than half of the county's {y} top-of-ticket votes: R, D, O (another party), or blank if no one cleared half."),
            (f"carried_{y}_pct", "number", f"That candidate's share of all {y} top-of-ticket votes in the county."),
        ]
        if "repeatPct" in c0 and y in (c0.get("repeatPct") or {}):
            cols.append((f"repeat_{y}_pct", "number", f"Percent of this year's ballots cast by someone who also voted early or by mail in {y} (county aggregate of a voter-id match; no voter-level data is published)."))
    cols.append(("as_of", "string", "Date the data runs through (constant, so a detached file still says what it describes)."))
    return cols


def county_row(c, fips, comparison_years, current_year, as_of):
    p = c["mailPipeline"]
    row = {
        "county_fips": fips,
        "county": c["name"],
        "active_voters": c["active"],
        "ballots": c["ballots"],
        "in_person": c["inPerson"],
        "mail": c["mail"],
        "turnout_pct_of_active": c["turnoutPct"],
    }
    if "adultPct" in c:
        row["citizen_adults_est"] = c["citizenAdults"]
        row["ballots_pct_of_citizen_adults_est"] = c["adultPct"]
        row["adults_25plus_bachelors_pct"] = c["bachelorsPct"]
    row.update({
        "mail_outstanding": p["outstanding"],
        "mail_rejected": suppress(p["rejected"]),
        "mail_cancelled_or_spoiled": suppress(p["cancelled"]),
        "mail_other": suppress(p["other"]),
    })
    for y in comparison_years:
        lean = (c.get("lean") or {}).get(y)
        row[f"ballots_{y}_same_point"] = c["prior"][y]
        row[f"ballots_{current_year}_at_{y}_point"] = c["atPoint"][y]
        row[f"early_share_{y}_pct"] = (c.get("earlyShare") or {}).get(y)
        row[f"carried_{y}"] = (lean["party"] if lean["majority"] else "") if lean else None
        row[f"carried_{y}_pct"] = lean["pct"] if lean else None
        if y in (c.get("repeatPct") or {}):
            row[f"repeat_{y}_pct"] = c["repeatPct"][y]
    row["as_of"] = as_of
    return row


def to_csv(columns, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r[c] for c in columns])
    return buf.getvalue().encode()


def json_schema(path, title, description, stability, columns, array_key):
    props = {}
    for name, typ, desc in columns:
        props[name] = {"type": [typ, "null"], "description": desc}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_url(path),
        "schemaVersion": SCHEMA_VERSION,
        "schemaStability": stability,
        "title": title,
        "description": description,
        "type": "object",
        "required": ["metadata", array_key],
        "properties": {
            "metadata": {"type": "object", "description": "What this file describes: the election, the as-of date, the comparison points, sources and caveats."},
            array_key: {"type": "array", "items": {"type": "object", "properties": props}},
        },
    }


def by_day_columns():
    return [
        ("election_year", "integer", "Election year of the row (this year, or a past year whose file is complete)."),
        ("county_fips", "string", "5-digit county FIPS code."),
        ("county", "string", "County name."),
        ("date", "string", "Calendar date (ISO) of the day. Blank when days_before is 45, which pools every earlier day."),
        ("days_before", "integer", "Days before election day. 45 means 45 or more."),
        ("in_person", "integer", "Accepted early in-person ballots returned that day."),
        ("mail", "integer", "Accepted mail and electronic ballots received that day."),
        ("ballots", "integer", "in_person + mail."),
    ]


def build_by_day(daily_doc, names_by_key, fips_by_key):
    """A complete grid: every county and every day from 45 days out to the last day counted, zero-filled.

    The source only lists days with at least one ballot; a consumer should not have to know that a missing row
    means zero. Past elections run to election day, this year to its as-of day."""
    rows = []
    for year in sorted(daily_doc["years"], reverse=True):
        y = daily_doc["years"][year]
        edate = dt.date.fromisoformat(y["electionDate"])
        last = (edate - dt.date.fromisoformat(y["asOf"])).days if "asOf" in y else 0
        src = {gen.key(name): days for name, days in y["counties"].items()}
        for key_ in sorted(names_by_key, key=lambda k: names_by_key[k]):
            have = {d: (ip, mail) for d, ip, mail in src.get(key_, [])}
            stray = sorted(d for d in have if d < last or d > gen.DAILY_WINDOW)
            if stray:
                raise ValueError(f"refusing to publish: {names_by_key[key_]} {year} has ballots on days {stray[:3]} outside {last}..{gen.DAILY_WINDOW}")
            for d in range(gen.DAILY_WINDOW, last - 1, -1):
                ip, mail = have.get(d, (0, 0))
                rows.append({
                    "election_year": int(year), "county_fips": fips_by_key[key_], "county": names_by_key[key_],
                    "date": None if d >= gen.DAILY_WINDOW else (edate - dt.timedelta(days=d)).isoformat(),
                    "days_before": d, "in_person": ip, "mail": mail, "ballots": ip + mail,
                })
    return rows


def check_consistency(totals_rows, by_day_rows, current_year):
    """The two tables must describe the same ballots, and no withheld value may be present."""
    errs = []
    sums = {}
    for r in by_day_rows:
        if r["election_year"] != int(current_year):
            continue
        s = sums.setdefault(r["county_fips"], [0, 0])
        s[0] += r["in_person"]
        s[1] += r["mail"]
    for r in totals_rows:
        got = sums.get(r["county_fips"])
        if got != [r["in_person"], r["mail"]]:
            errs.append(f"{r['county']}: county-by-day adds to {got} but county-totals has {[r['in_person'], r['mail']]}")
        for col in SENSITIVE:
            v = r.get(col)
            if v is not None and 0 < v < SUPPRESS_BELOW:
                errs.append(f"{r['county']}: {col} = {v} must be withheld")
    if errs:
        raise ValueError("refusing to publish: " + "; ".join(errs[:6]))


def build_artifacts(totals, daily, fips_by_key, dictionary=None):
    md = totals["metadata"]
    election = dt.date.fromisoformat(md["electionDate"])
    cur = str(election.year)
    as_of = md["asOf"]
    if daily["years"][cur]["asOf"] != as_of:
        raise ValueError(f"refusing to publish: county-by-day runs through {daily['years'][cur]['asOf']} but county-totals through {as_of}")
    comps = sorted(md["comparisons"])
    counties = totals["counties"]
    missing = [c["name"] for c in counties if gen.key(c["name"]) not in fips_by_key]
    if missing:
        raise ValueError(f"refusing to publish: no FIPS code for {missing[:5]}")

    cols = base_columns(comps, cur, counties)
    names = [c[0] for c in cols]
    rows = [county_row(c, fips_by_key[gen.key(c["name"])], comps, cur, as_of) for c in sorted(counties, key=lambda c: fips_by_key[gen.key(c["name"])])]
    for r in rows:
        extra = set(r) - set(names)
        if extra:
            raise ValueError(f"refusing to publish: row has columns the schema does not: {sorted(extra)}")
    by_day = build_by_day(daily, {gen.key(c["name"]): c["name"] for c in counties}, fips_by_key)
    check_consistency(rows, by_day, cur)

    folder = f"early-vote/{cur}-general"
    sw = totals["statewide"]
    meta = {
        "schemaVersion": SCHEMA_VERSION,
        "election": {"date": md["electionDate"], "year": int(cur), "type": "general"},
        "asOf": as_of,
        "daysBeforeElection": md["daysBeforeElection"],
        "dataGeneratedAt": md["generatedAt"],
        "comparisons": md["comparisons"],
        "suppression": f"Counts of 1 to {SUPPRESS_BELOW - 1} in mail_rejected, mail_cancelled_or_spoiled and mail_other are withheld (blank). Accepted ballots and all other columns are published as counted.",
        "source": "Georgia Secretary of State absentee and early-voting files, active voter registration table and certified results; county Census figures from the U.S. Census Bureau American Community Survey, compiled by Georgia Civic Data (georgiacivicdata.org, CC BY 4.0).",
        "notes": [
            "The Secretary of State's file runs through the previous day, so asOf is the last full day counted.",
            "Past elections are compared at the same number of days before election day. 2022 is compared earlier (see comparisons) because the Secretary of State's 2022 absentee file is missing most Fulton and Gwinnett ballots after 2022-10-22.",
            "Georgia voters do not register by party. These columns say how each county voted in past elections, not which party's voters voted early.",
        ],
    }
    if md.get("countyContext"):
        meta["countyContext"] = md["countyContext"]
    totals_doc = {"metadata": meta, "statewide": {
        "ballots": sw["ballots"], "in_person": sw["inPerson"], "mail": sw["mail"], "active_voters": sw["active"],
        "turnout_pct_of_active": sw["turnoutPct"], "mail_pipeline": sw["mailPipeline"],
        **({"citizen_adults_est": sw["citizenAdults"], "ballots_pct_of_citizen_adults_est": sw["adultPct"]} if "adultPct" in sw else {}),
    }, "counties": rows}
    by_day_meta = {
        "schemaVersion": SCHEMA_VERSION,
        "election": meta["election"], "asOf": as_of, "dataGeneratedAt": daily["metadata"]["generatedAt"],
        "years": sorted(daily["years"]),
        "note": daily["metadata"]["note"],
        "source": meta["source"],
    }
    by_day_doc = {"metadata": by_day_meta, "rows": by_day}

    artifacts = {
        f"{folder}/county-totals.json": build_json(totals_doc),
        f"{folder}/county-totals.csv": to_csv(names, rows),
        f"{folder}/county-by-day.json": build_json(by_day_doc),
        f"{folder}/county-by-day.csv": to_csv([c[0] for c in by_day_columns()], by_day),
        f"{folder}/county-totals.schema.json": build_json(json_schema(
            f"{folder}/county-totals.schema.json", "Georgia early voting: county totals",
            "One row per Georgia county: accepted early and mail ballots so far, the mail pipeline, and comparisons with past elections at the same point before election day.",
            STABILITY["totals"], cols, "counties")),
        f"{folder}/county-by-day.schema.json": build_json(json_schema(
            f"{folder}/county-by-day.schema.json", "Georgia early voting: county by day",
            "Accepted ballots per county and day before election day, for this election and any past election whose Secretary of State file is complete.",
            STABILITY["byDay"], by_day_columns(), "rows")),
        f"{folder}/README.md": readme(cur, folder).encode(),
    }
    if dictionary:
        artifacts[f"{folder}/source-data-dictionary.md"] = dictionary
    return artifacts


def readme(year, folder):
    return f"""# Georgia early voting, {year} general election

County-level counts of early in-person and mail ballots, refreshed whenever the Secretary of State posts a new
file. Powers the [Early Voting Turnout page](https://www.votega.org/ga-early-vote/) on VoteGA.org.

| File | What it is |
|---|---|
| `county-totals.csv` / `.json` | One row per county: ballots, in person and mail, the mail pipeline, turnout, and comparisons with past elections at the same point before election day |
| `county-by-day.csv` / `.json` | Accepted ballots per county per day before election day, for {year} and for past elections whose source file is complete |
| `*.schema.json` | JSON Schema for each JSON file; every column is described there |
| `source-data-dictionary.md` | What each field means in the Secretary of State's source files, and the traps in them |

## Read this first

- **Every file says what it runs through.** `asOf` (and the `as_of` column) is the last full day counted. The
  Secretary of State's file runs through the previous day, and this dataset is refreshed by hand, so it can lag the
  SoS dashboard by a day or more.
- **Elections are compared at the same number of days before election day**, not on the same date. The comparison
  days are in `metadata.comparisons`.
- **2022 is compared at 17 days out and has no day-by-day file.** The Secretary of State's 2022 absentee file is missing
  most Fulton and Gwinnett ballots after 2022-10-22, and there is no other download for it.
- **Georgia voters do not register by party**, so this data cannot say which party's voters voted early. The
  `carried_<year>` columns say how the county voted in that year's top-of-ticket race.
- **`citizen_adults_est` is an estimate** (adults 18 and over minus non-citizen residents of every age), so it runs
  slightly low. Active voters is the more precise denominator.
- **Small counts are withheld.** A blank in `mail_rejected`, `mail_cancelled_or_spoiled` or `mail_other` means 1 to 9,
  not zero.

## Provenance

Everything here is a county-level aggregate derived from the Secretary of State's absentee-ballot and voter-history downloads, its county active/inactive voter counts and its certified results. It contains no elector-level data (no names, addresses or voter IDs), nothing below the county, and it does not use the Secretary of State's voter list products (the Voter List and Statewide Voter File ordered under O.C.G.A. § 21-2-225).

## What is not here

No voter-level data, nothing below the county, and no demographics. The underlying files contain names and addresses
and are never published.

## Credits and terms

Secretary of State files and results: Georgia Secretary of State. County Census figures: U.S. Census Bureau,
American Community Survey, compiled by [Georgia Civic Data](https://georgiacivicdata.org) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).
This dataset is licensed CC BY-SA 4.0; see `LICENSE` and `NOTICE.md` at the repository root.
Generated by <https://github.com/Votega/votega.org> (`scripts/publish_early_vote.py`).
"""


def load_sources():
    totals = json.load(open(SRC_TOTALS, encoding="utf-8"))
    daily = json.load(open(SRC_DAILY, encoding="utf-8"))
    ctx = json.load(open(SRC_CONTEXT, encoding="utf-8"))
    fips = {gen.key(c["name"]): f for f, c in ctx["counties"].items()}
    dictionary = open(SRC_DICTIONARY, "rb").read() if os.path.exists(SRC_DICTIONARY) else None
    return totals, daily, fips, dictionary


def validate(artifacts):
    folder = next(p.rsplit("/", 1)[0] for p in artifacts if p.endswith("county-totals.json"))
    min_items(f"{folder}/county-totals.json", "counties", minimum=159)(artifacts)
    min_items(f"{folder}/county-by-day.json", "rows", minimum=159 * 40)(artifacts)


def main():
    artifacts = build_artifacts(*load_sources())
    publish_or_dry_run(REPO, artifacts, TOKEN_ENV, validate=validate)


if __name__ == "__main__":
    main()
