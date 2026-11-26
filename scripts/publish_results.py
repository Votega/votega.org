#!/usr/bin/env python3
"""Publish certified election results (vote counts) to Votega/ga-races-elections.

Sources: _data/election_results/<key>.json (the files the results pages render, built by
build_results_json.py), each results page's front matter, _data/results_updated.json, and,
where committed, _sources/election_results/<key>-breakdown.json (county and vote-method figures,
built by distill_results_breakdown.py).
Artifacts, one permanent folder per election:
  results/<election>/results.json         one entry per contest, with its candidates
  results/<election>/results.csv          one row per contest and candidate
  results/<election>/results.schema.json  JSON Schema for results.json
  results/<election>/county-results.csv   one row per county, contest and candidate (needs a breakdown)
  data/results/manifest.json              every published election

ONLY CERTIFIED ELECTIONS ARE PUBLISHED. The gate is the results page's own `status: certified`
front matter, the same one the site shows readers. The page's `results_folder:` names its
folder, e.g. 2026-general.

A folder outlives its source: the next cycle reuses the data keys, so folders already published
(read from OUT_DIR, a checkout of the target repo) are carried into the manifest unchanged.
That is why this publisher is git-based only: the workflow commits what it writes to OUT_DIR.
"""
import csv
import io
import json
import os
import re
import sys

from lib.ga_county_fips import GA_COUNTY_FIPS
from lib.race_winners import parse_front_matter
from lib.sibling_publish import add_dataset_manifest, build_json, publish_or_dry_run

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

REPO = "Votega/ga-races-elections"
TOKEN_ENV = "GA_RACES_TOKEN"
RAW_BASE = "https://raw.githubusercontent.com/Votega/ga-races-elections/main"
SITE = "https://www.votega.org"
SOURCE = "Georgia Secretary of State"
SCHEMA_VERSION = "1.1.0"
FILES = ("results.json", "results.csv", "results.schema.json", "county-results.csv")
FOLDER_RE = re.compile(r"^\d{4}-[a-z0-9]+(-[a-z0-9]+)*$")

METHODS = ["electionDay", "advanceVoting", "absenteeByMail", "provisional"]

# Columns are only ever APPENDED, so a consumer reading by position keeps working.
RESULTS_COLUMNS = ["election", "office", "district", "party", "candidate", "votes", "totalVotes",
                   "incumbent", "winner", "electionDate", "section", "contestId", "contestParty",
                   "outcome", "advancedToRunoff", "status", *METHODS]
COUNTY_COLUMNS = ["election", "county", "countyFips", "office", "district", "party", "candidate",
                  "votes", *METHODS, "contestId", "section", "electionDate", "status"]

PARTIES = {"rep": "Republican", "dem": "Democrat", "ind": "Independent"}
PARTY_SUFFIX_RE = re.compile(r"\s*\((Dem|Rep|Ind)\)\s*$", re.IGNORECASE)
CHAMBERS = {"us-house": "U.S. House", "state-senate": "Georgia State Senate",
            "state-house": "Georgia House of Representatives"}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def results_pages(root):
    """Front matter of every election-results page stub."""
    pages = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(root, name), encoding="utf-8") as f:
            fm = parse_front_matter(f.read())
        if fm.get("layout") == "election_results" and fm.get("results_data"):
            pages.append(fm)
    return pages


def candidate_party(name, contest_party):
    """(name without a party suffix, party or None). A general-election contest carries each
    candidate's party as a "(Dem)" suffix; a primary contest carries it for the whole contest."""
    m = PARTY_SUFFIX_RE.search(name)
    if m:
        return name[:m.start()].strip(), PARTIES[m.group(1).lower()]
    return name, PARTIES.get(contest_party)


def office_and_district(section, office):
    m = re.search(r"District\s+(\d+)", office)
    district = int(m.group(1)) if m else None
    chamber = CHAMBERS.get(section)
    if not chamber:
        return office, district
    if "special" in office.lower():
        return f"{chamber} (special election)", district
    return (chamber if re.fullmatch(r"District\s+\d+", office) else office), district


def read_contest(contest, mode, advances, where):
    """(outcome, total or None, [(votes, winner, advancedToRunoff)]) in the source's order.

    The same reading as assets/scripts/results-contest.js: in `round` mode a leader needs more
    than half or the top finishers go to a runoff; in `final` mode the leader wins."""
    cands = contest["candidates"]
    total = contest.get("totalVotes") or 0
    cast = sum(c["votes"] for c in cands)
    if cast > total:
        raise ValueError(f"refusing to publish {where}: candidate votes ({cast}) exceed the "
                         f"contest total ({total})")
    if not total:
        # One name and no count: the export did not report the contest. Never publish that as 0.
        if len(cands) != 1:
            raise ValueError(f"refusing to publish {where}: certified, but {len(cands)} "
                             "candidates and no votes")
        return "not-reported", None, [(None, None, False)]
    if len(cands) == 1:
        return "uncontested", total, [(cast, True, False)]
    ranked = sorted(range(len(cands)), key=lambda i: cands[i]["votes"], reverse=True)
    if mode == "final" or cands[ranked[0]]["votes"] * 2 > total:
        if cands[ranked[0]]["votes"] == cands[ranked[1]]["votes"]:
            raise ValueError(f"refusing to publish {where}: tie for first")
        return "decided", total, [(c["votes"], i == ranked[0], False) for i, c in enumerate(cands)]
    through = set(ranked[:advances])
    return "runoff", total, [(c["votes"], False, i in through) for i, c in enumerate(cands)]


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_contests(sections, mode, advances, folder):
    contests = []
    for section in sections:
        for race in section.get("races") or []:
            office, district = office_and_district(section["id"], race["office"])
            for contest in race.get("contests") or []:
                where = f"{folder} {section['id']} {race['office']!r}"
                outcome, total, reads = read_contest(contest, mode, advances, where)
                candidates = []
                for c, (votes, winner, advanced) in zip(contest["candidates"], reads):
                    name, party = candidate_party(c["name"], contest.get("party"))
                    candidates.append({"candidate": name, "party": party, "votes": votes,
                                       "incumbent": bool(c.get("incumbent")), "winner": winner,
                                       "advancedToRunoff": advanced, **dict.fromkeys(METHODS)})
                ballot = contest.get("party")
                contest_id = "-".join(filter(None, [
                    section["id"], _slug(race["office"]), ballot if ballot in PARTIES else None]))
                contests.append({"contestId": contest_id, "section": section["id"], "office": office,
                                 "district": district, "contestParty": PARTIES.get(ballot),
                                 "outcome": outcome, "totalVotes": total, "candidates": candidates})
    # Several seats can share one office name (superior court); number those.
    ids = [c["contestId"] for c in contests]
    seen = {}
    for c in contests:
        base = c["contestId"]
        if ids.count(base) > 1:
            seen[base] = seen.get(base, 0) + 1
            c["contestId"] = f"{base}-{seen[base]}"
    return contests


def _cell(value):
    return "" if value is None else value


def _methods(split, votes, where):
    """{method: votes}, all None where no split is reported."""
    if split is None:
        return dict.fromkeys(METHODS)
    if len(split) != len(METHODS) or sum(split) != votes:
        raise ValueError(f"refusing to publish {where}: the breakdown's vote methods do not add up")
    return dict(zip(METHODS, split))


def apply_breakdown(contests, breakdown, folder):
    """Fill each candidate's vote-method fields from the breakdown and return the county rows.

    A contest is matched by its section and its candidates' certified totals, so a breakdown built
    from different counts (an unofficial export, another election) cannot be attached."""
    if breakdown.get("methods") != METHODS:
        raise ValueError(f"refusing to publish {folder}: the breakdown's methods are not {METHODS}")

    def key(section, pairs):
        return section, tuple(sorted(pairs))

    source = {}
    for item in breakdown["contests"]:
        k = key(item["section"], [(c["name"], c["votes"]) for c in item["candidates"]])
        if k in source:
            raise ValueError(f"refusing to publish {folder}: two breakdown contests look like {item['office']!r}")
        source[k] = item
    rows = []
    for contest in contests:
        if contest["totalVotes"] is None:
            continue
        where = f"{folder} {contest['section']} {contest['office']!r} {contest['district'] or ''}".rstrip()
        names = [c["candidate"] for c in contest["candidates"]]
        item = source.pop(key(contest["section"],
                              [(c["candidate"], c["votes"]) for c in contest["candidates"]]), None)
        if item is None or len(set(names)) != len(names):
            raise ValueError(f"refusing to publish {where}: no breakdown contest matches its certified totals")
        position = {c["name"]: i for i, c in enumerate(item["candidates"])}
        added = dict.fromkeys(names, 0)
        for cand in contest["candidates"]:
            split = item["candidates"][position[cand["candidate"]]]["methods"]
            cand.update(_methods(split, cand["votes"], where))
        for county, values in sorted(item["counties"].items()):
            fips = GA_COUNTY_FIPS.get(county.lower().replace(" ", "-"))
            if not fips or len(values) != len(names):
                raise ValueError(f"refusing to publish {where}: unknown or incomplete county {county!r}")
            for cand in contest["candidates"]:
                votes, split = values[position[cand["candidate"]]]
                added[cand["candidate"]] += votes
                rows.append({**contest, **cand, "county": county, "countyFips": fips, "votes": votes,
                             **_methods(split, votes, f"{where} in {county}")})
        for cand in contest["candidates"]:
            if added[cand["candidate"]] != cand["votes"]:
                raise ValueError(f"refusing to publish {where}: counties add up to {added[cand['candidate']]} "
                                 f"for {cand['candidate']}, certified {cand['votes']}")
    extra = [i["office"] for i in source.values() if any(c["votes"] for c in i["candidates"])]
    if extra:
        raise ValueError(f"refusing to publish {folder}: breakdown contests that are not published: {extra[:5]}")
    return rows


def county_csv(meta, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, COUNTY_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        row = {**r, "election": meta["election"], "electionDate": meta["electionDate"],
               "status": meta["status"]}
        w.writerow({k: _cell(row[k]) for k in COUNTY_COLUMNS})
    return buf.getvalue().encode("utf-8")


def results_csv(doc):
    meta = doc["metadata"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, RESULTS_COLUMNS, lineterminator="\n")
    w.writeheader()
    for contest in doc["contests"]:
        for cand in contest["candidates"]:
            row = {**contest, **cand, "election": meta["election"],
                   "electionDate": meta["electionDate"], "status": meta["status"]}
            w.writerow({k: _cell(row[k]) for k in RESULTS_COLUMNS})
    return buf.getvalue().encode("utf-8")


def schema(schema_path):
    def obj(properties, optional=()):
        return {"type": "object", "required": [p for p in properties if p not in optional],
                "properties": properties}

    def field(types, description):
        return {"type": types, "description": description}

    candidate = obj({
        "candidate": field("string", "Ballot name, without the party suffix."),
        "party": field(["string", "null"], "Candidate's party; null for nonpartisan contests and ballot questions."),
        "votes": field(["integer", "null"], "Votes received; null when the contest was not reported."),
        "incumbent": field("boolean", "Marked as the incumbent on the ballot."),
        "winner": field(["boolean", "null"], "Won this contest outright (in a primary: won the nomination). "
                                             "For a ballot question, the option with more votes. Null when not reported."),
        "advancedToRunoff": field("boolean", "Went on to a runoff from this contest."),
        **{method: field(["integer", "null"], f"Votes cast by {label}; null where no split is available.")
           for method, label in zip(METHODS, ("election-day voting", "advance (early in-person) voting",
                                              "absentee ballot by mail", "provisional ballot"))},
    }, optional=METHODS)
    contest = obj({
        "contestId": field("string", "Unique within the election."),
        "section": {"type": "string", "enum": ["statewide", "us-house", "state-senate", "state-house", "courts", "measures"]},
        "office": field("string", "Office, chamber or ballot question."),
        "district": field(["integer", "null"], "District number, where the office has one."),
        "contestParty": field(["string", "null"], "Party ballot, for a one-party contest; null otherwise."),
        "outcome": {"type": "string", "enum": ["decided", "uncontested", "runoff", "not-reported"],
                    "description": "not-reported: the Secretary of State export carried no count for it."},
        "totalVotes": field(["integer", "null"], "Votes cast in the contest; null when not reported."),
        "candidates": {"type": "array", "items": candidate},
    })
    metadata = {"type": "object", "properties": {
        "election": field("string", "The folder name under results/."),
        "title": {"type": "string"},
        "electionDate": field("string", "ISO date of the election."),
        "status": {"type": "string", "enum": ["certified"]},
        "source": {"type": "string"},
        "resultsPage": {"type": "string"},
        "generatedAt": field("string", "When the underlying results data was built."),
        "schemaVersion": {"type": "string"},
        "contestCount": {"type": "integer"},
        "countyResults": field("boolean", "county-results.csv is published and the vote-method fields are filled."),
    }}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{RAW_BASE}/{schema_path}",
        "schemaVersion": SCHEMA_VERSION,
        "schemaStability": "Fields and CSV columns are only ever added (CSV columns at the end). "
                           "Every file here describes one certified election.",
        "title": "Georgia certified election results",
        **obj({"metadata": metadata, "contests": {"type": "array", "items": contest}}),
    }


def build_election(root, fm, stamps):
    """{path: bytes} for one certified results page."""
    key = fm["results_data"]
    folder = fm.get("results_folder") or ""
    date = fm.get("election_date") or ""
    if not FOLDER_RE.match(folder) or not folder.startswith(date[:4] + "-"):
        raise ValueError(f"refusing to publish {key}: results_folder must look like "
                         f"'{date[:4]}-general' (got {folder!r})")
    generated = (stamps.get(key) or {}).get("iso")
    if not generated:
        raise ValueError(f"refusing to publish {key}: no build time in _data/results_updated.json")
    contests = build_contests(_load(os.path.join(root, "_data", "election_results", key + ".json")),
                              fm.get("results_mode") or "round",
                              int(fm.get("runoff_advances") or 2), folder)
    if not any(c["totalVotes"] for c in contests):
        raise ValueError(f"refusing to publish {key}: marked certified but holds no votes")
    county_rows = None
    breakdown_path = os.path.join(root, "_sources", "election_results", key + "-breakdown.json")
    if os.path.isfile(breakdown_path):
        breakdown = _load(breakdown_path)
        if breakdown.get("electionDate") != date:
            raise ValueError(f"refusing to publish {key}: {key}-breakdown.json is for the "
                             f"{breakdown.get('electionDate')} election, the page for {date}")
        county_rows = apply_breakdown(contests, breakdown, folder)
    doc = {"metadata": {"election": folder, "title": fm.get("heading") or fm.get("title") or folder,
                        "electionDate": date, "status": "certified", "source": SOURCE,
                        "resultsPage": SITE + (fm.get("permalink") or f"/{key}/"),
                        "generatedAt": generated, "schemaVersion": SCHEMA_VERSION,
                        "contestCount": len(contests), "countyResults": county_rows is not None},
           "contests": contests}
    base = f"results/{folder}"
    files = {f"{base}/results.json": build_json(doc),
             f"{base}/results.csv": results_csv(doc),
             f"{base}/results.schema.json": build_json(schema(f"{base}/results.schema.json"))}
    if county_rows is not None:
        files[f"{base}/county-results.csv"] = county_csv(doc["metadata"], county_rows)
    return files


def published_folders(published_dir):
    """{folder: {path: bytes}} for elections already in the target repo checkout."""
    base = os.path.join(published_dir or "", "results")
    if not published_dir or not os.path.isdir(base):
        return {}
    out = {}
    for folder in sorted(os.listdir(base)):
        paths = [os.path.join(base, folder, name) for name in FILES]
        if not os.path.isfile(paths[0]):
            continue
        out[folder] = {}
        for name, path in zip(FILES, paths):
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    out[folder][f"results/{folder}/{name}"] = f.read()
    return out


def build_artifacts(root=ROOT, published_dir=None):
    stamps = _load(os.path.join(root, "_data", "results_updated.json"))
    built = {}
    for fm in results_pages(root):
        if fm.get("status") != "certified":
            print(f"  skipped {fm['results_data']}: status is {fm.get('status')!r}, not certified")
            continue
        files = build_election(root, fm, stamps)
        folder = fm["results_folder"]
        if folder in built:
            raise ValueError(f"refusing to publish: two results pages use results_folder {folder}")
        built[folder] = files
    if not built:
        raise ValueError("refusing to publish: no certified results page found")

    published = published_folders(published_dir)
    for folder, files in built.items():
        if folder in published:
            path = f"results/{folder}/results.json"
            before = json.loads(published[folder][path])["metadata"]["electionDate"]
            after = json.loads(files[path])["metadata"]["electionDate"]
            if before != after:
                raise ValueError(f"refusing to publish: results/{folder}/ holds the {before} election; "
                                 f"it cannot be rewritten for {after}. Give the page its own results_folder.")
            orphaned = sorted(set(published[folder]) - set(files))
            if orphaned:
                raise ValueError(f"refusing to publish: {orphaned} is already published but would not be "
                                 "rebuilt. Restore its source file under _sources/election_results/.")
    elections = {**published, **built}

    out, metas, rows = {}, [], 0
    for folder in sorted(elections):
        out.update(elections[folder])
        doc = json.loads(elections[folder][f"results/{folder}/results.json"])
        metas.append(doc["metadata"])
        rows += sum(len(c["candidates"]) for c in doc["contests"])

    descriptions = {"results.json": "Certified results, one entry per contest.",
                    "results.csv": "Certified results as a spreadsheet, one row per contest and candidate.",
                    "results.schema.json": "JSON Schema for results.json.",
                    "county-results.csv": "Certified results by county and vote method, one row per "
                                          "county, contest and candidate."}
    add_dataset_manifest(
        out, REPO, "results",
        title="Georgia certified election results",
        description="Certified vote counts for Georgia elections, one folder per election, with county "
                    "and vote-method figures where available.",
        generated_at=max(m["generatedAt"] for m in metas),
        update_cadence="After the Secretary of State certifies an election.",
        row_count=rows,
        schema_version=SCHEMA_VERSION,
        source=SOURCE,
        coverage={"elections": [{k: m[k] for k in ("election", "electionDate", "status")}
                                for m in metas]},
        files=[{"path": p, "description": descriptions[p.rsplit("/", 1)[-1]]} for p in sorted(out)],
    )
    return out


def main():
    if os.environ.get(TOKEN_ENV):
        sys.exit(f"publish_results.py writes to OUT_DIR (a checkout of {REPO}) and is committed with git; "
                 f"unset {TOKEN_ENV}.")
    out_dir = os.environ.get("OUT_DIR") or "out"
    publish_or_dry_run(REPO, build_artifacts(ROOT, out_dir), TOKEN_ENV)


if __name__ == "__main__":
    main()
