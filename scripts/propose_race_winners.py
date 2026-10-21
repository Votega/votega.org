#!/usr/bin/env python3
"""Propose each race's winner from CERTIFIED results, for a person to review and apply.

The candidate pages redirect a winner to their officeholder page and retire everyone else once
a race carries `status: "certified"` and `winner: {candidateId, ...}` in assets/data/races.json
(scripts/lib/candidate_standing.py). Nothing recorded those. This reads the same results data the
results pages render (_data/election_results/*.json) and works out the winners; the rules live in
scripts/lib/race_winners.py (certified only, tied by election date, majority required, one
unambiguous name match, never overwrite a different winner).

It is a proposal tool. The default run changes nothing and prints a report: what it would
record, the races that went (or are going) to a runoff, and everything it declined to decide with
the reason. `--apply` records only the unambiguous ones, behind the races_guard check, and leaves
every flagged race for a person. Review the diff and commit it like any other data change.

Usage:
  python scripts/propose_race_winners.py              # report only
  python scripts/propose_race_winners.py --preview-unofficial   # election night: treat counts as
                                                      # final to check names/structure (report
                                                      # only; refuses --apply)
  python scripts/propose_race_winners.py --apply      # write races.json
  python scripts/propose_race_winners.py --json out.json

Run it after the Secretary of State certifies and the results page's `status:` is `certified`.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import atomic_write  # noqa: E402
from lib.race_winners import apply_changes, parse_front_matter, plan_changes, propose  # noqa: E402
from lib.races_guard import RacesGuardError, assert_only_winners_changed  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_PATH = os.path.join(ROOT, "assets", "data", "races.json")
RESULTS_DIR = os.path.join(ROOT, "_data", "election_results")


def load_races():
    with open(RACES_PATH, encoding="utf-8", newline="") as fh:
        text = fh.read()
    return json.loads(text), text


def render(doc: dict) -> str:
    """races.json's exact on-disk shape: 2-space indent, CRLF, no trailing newline."""
    return json.dumps(doc, indent=2, ensure_ascii=False).replace("\n", "\r\n")


def load_members():
    """{bioguide id: {name, party}} for the sitting delegation, so an incumbent the ballot lists
    only by member id can be matched against a result row by name. Empty if the roster is absent."""
    path = os.path.join(ROOT, "assets", "data", "current-members.json")
    try:
        with open(path, encoding="utf-8") as fh:
            members = json.load(fh).get("members") or []
    except (OSError, ValueError):
        return {}
    return {m["bioguideId"]: {"name": f"{m.get('firstName') or ''} {m.get('lastName') or ''}".strip(),
                              "party": m.get("partyName")}
            for m in members if m.get("bioguideId") and (m.get("firstName") or m.get("lastName"))}


def load_result_sets():
    """Every results page that decides an election (general / special, and their runoffs).

    Primaries never decide who holds an office, so they are left out. The page's front matter
    supplies the date and certification status; the data file supplies the counts.
    """
    sets = []
    for path in sorted(glob.glob(os.path.join(ROOT, "*.html"))):
        with open(path, encoding="utf-8") as fh:
            head = fh.read(4000)
        fm = parse_front_matter(head)
        key = fm.get("results_data")
        if fm.get("layout") != "election_results" or not key or "primary" in key:
            continue
        data_path = os.path.join(RESULTS_DIR, key + ".json")
        if not os.path.exists(data_path) or not fm.get("election_date"):
            continue
        with open(data_path, encoding="utf-8") as fh:
            sections = json.load(fh)
        sets.append({"data_key": key, "election_date": fm["election_date"],
                     "status": fm.get("status", "unofficial"), "sections": sections})
    return sets


def report(result, changes, conflicts) -> str:
    out = []
    out.append(f"Would record {len(changes)} winner(s):")
    for p in sorted(changes, key=lambda p: p["raceId"]):
        w = p["winner"]
        out.append(f"  {p['raceId']:34} {w['name']} ({w.get('party') or 'no party'}) "
                   f"{p['share']:.1%} of {p['total']:,}  [{p['phase']}, {p['dataKey']}]")
    if conflicts:
        out.append(f"\nCONFLICTS with a winner already recorded ({len(conflicts)}), left untouched:")
        for c in conflicts:
            out.append(f"  {c['raceId']}: recorded {c['recorded']!r}, results say {c['proposed']!r}")
    if result["runoffs"]:
        out.append(f"\nNo majority, so a runoff ({len(result['runoffs'])}):")
        for r in sorted(result["runoffs"].values(), key=lambda r: r["raceId"]):
            out.append(f"  {r['raceId']:34} leader {r['leader']} at {r['share']:.1%}")
    if result["flagged"]:
        out.append(f"\nNeeds a person ({len(result['flagged'])}), NOT recorded:")
        for f in result["flagged"]:
            out.append(f"  {f.get('raceId') or f.get('office')}: {f['reason']}")
    if result.get("unhandled"):
        out.append(f"\n{len(result['unhandled'])} judicial race(s) not handled (judicial results are not matched yet).")
    if result["skipped"]:
        out.append("\nSkipped (not certified, so they decide nothing):")
        for s in result["skipped"]:
            out.append(f"  {s['data_key']}: status {s['status']!r}, {s['contests']} contests, {s['election_date']}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write races.json (default: report only)")
    ap.add_argument("--json", metavar="PATH", help="also write the full proposal as JSON")
    ap.add_argument("--preview-unofficial", action="store_true",
                    help="REPORT ONLY: treat unofficial counts as final, to check name matching and "
                         "structure against election night's real file before certification")
    args = ap.parse_args()
    if args.preview_unofficial and args.apply:
        ap.error("--preview-unofficial can never be combined with --apply: unofficial counts can still move")

    doc, text = load_races()
    if render(doc) != text:
        print("races.json is not in its canonical shape (2-space, CRLF, no trailing newline); "
              "refusing to rewrite it, since the diff would be noise. Format it first.", file=sys.stderr)
        return 1
    sets = load_result_sets()
    if args.preview_unofficial:
        sets = [{**s, "status": "certified"} for s in sets]
        print("PREVIEW: unofficial counts are being treated as final. Nothing here is a result; "
              "use it to check names and structure only.\n")
    result = propose(sets, doc["races"], load_members())
    changes, conflicts = plan_changes(result["proposals"], doc["races"])
    print(report(result, changes, conflicts))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({**result, "changes": changes, "conflicts": conflicts}, fh, indent=2, ensure_ascii=False)

    if not args.apply:
        print("\n(report only; --apply records the winners listed above)")
        return 0
    if not changes:
        print("\nNothing to record.")
        return 0
    before = copy.deepcopy(doc)
    ids = apply_changes(doc, changes)
    doc["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        assert_only_winners_changed(before, doc, ids)
    except RacesGuardError as exc:
        print(f"ABORTED, races.json untouched: {exc}", file=sys.stderr)
        return 1
    with atomic_write(RACES_PATH, newline="") as fh:
        fh.write(render(doc))
    print(f"\nRecorded {len(ids)} winner(s) in races.json. Review the diff, then commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
