#!/usr/bin/env python3
"""Keep the county and vote-method figures from a Secretary of State JSON results export.

    python scripts/distill_results_breakdown.py <export.json> <data_key>

    python scripts/distill_results_breakdown.py ~/Downloads/export-11032026GeneralAndSpecialElection.json ga-general-2026-results

Writes _sources/election_results/<data_key>-breakdown.json, which publish_results.py turns into
county-results.csv and the vote-method columns of results.csv. Run it on the CERTIFIED export:
the publisher refuses figures that do not match the certified totals.

The export itself (https://results.sos.ga.gov/cdn/results/Georgia/export-<MMDDYYYY><Name>.json)
is 25-160 MB, mostly precinct results, so it is not committed. Only the contests the results pages
publish are kept; precinct results are dropped. A county that reports no vote-method split keeps
its total with `methods: null`, never zeros.
"""
import json
import os
import sys

from build_results_json import classify, parse_candidate_name
from lib.atomic_io import write_json_atomic
from publish_results import METHODS, ROOT, candidate_party

GROUPS = ("Election Day", "Advance Voting", "Absentee by Mail", "Provisional")  # in METHODS order


def _split(option, where):
    """[votes by method], or None where the export reports no split."""
    groups = {g.get("groupName"): g.get("voteCount") for g in option.get("groupResults") or []}
    unknown = sorted(set(groups) - set(GROUPS), key=str)
    if unknown:
        raise ValueError(f"{where}: unknown vote method(s) {unknown}")
    values = [groups.get(g) for g in GROUPS]
    if all(v is None for v in values):
        return None
    if None in values or sum(values) != (option.get("voteCount") or 0):
        raise ValueError(f"{where}: the vote method figures are partly blank or do not add up to the total")
    return values


def _name(option):
    return candidate_party(parse_candidate_name((option.get("name") or "").strip())[0], None)[0]


def distill(payload):
    items = ((payload.get("results") or {}).get("ballotItems")) or []
    counties = payload.get("localResults") or []
    if not items or not payload.get("electionDate"):
        raise ValueError("this is not the Secretary of State JSON results export")
    if not counties:
        raise ValueError("the export carries no county results (localResults)")
    contests = {}
    for item in items:
        office = (item.get("name") or "").strip()
        section = classify(office)
        if section is None:
            continue
        options = item.get("ballotOptions") or []
        contests[item["id"]] = {
            "section": section, "office": office,
            "ids": [o["id"] for o in options],
            "candidates": [{"name": _name(o), "votes": o.get("voteCount") or 0,
                            "methods": _split(o, f"{office} / {_name(o)}")} for o in options],
            "counties": {},
        }
    for county in counties:
        name = (county.get("name") or "").removesuffix(" County").strip()
        for item in county.get("ballotItems") or []:
            contest = contests.get(item.get("id"))
            if contest is None:
                continue
            where = f"{contest['office']} in {name}"
            by_id = {o["id"]: o for o in item.get("ballotOptions") or []}
            if set(by_id) != set(contest["ids"]):
                raise ValueError(f"{where}: the county's candidates differ from the contest's")
            contest["counties"][name] = [
                [by_id[i].get("voteCount") or 0, _split(by_id[i], f"{where} / {_name(by_id[i])}")]
                for i in contest["ids"]]
    for contest in contests.values():
        for n, cand in enumerate(contest["candidates"]):
            added = sum(rows[n][0] for rows in contest["counties"].values())
            if added != cand["votes"]:
                raise ValueError(f"{contest['office']} / {cand['name']}: counties add up to {added}, "
                                 f"the contest says {cand['votes']}")
        del contest["ids"]
        contest["counties"] = dict(sorted(contest["counties"].items()))
    return {"electionDate": payload["electionDate"], "createdAt": payload.get("createdAt"),
            "methods": list(METHODS), "contests": list(contests.values())}


def main(argv):
    if len(argv) != 2:
        sys.exit("Usage: python scripts/distill_results_breakdown.py <export.json> <data_key>")
    path, key = argv
    with open(path, encoding="utf-8") as f:
        out = distill(json.load(f))
    dest = os.path.join(ROOT, "_sources", "election_results", f"{key}-breakdown.json")
    write_json_atomic(dest, out, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(out['contests'])} contest(s), election {out['electionDate']}, export built {out['createdAt']}")
    print(f"Wrote: {dest} ({os.path.getsize(dest):,} bytes)")


if __name__ == "__main__":
    main(sys.argv[1:])
