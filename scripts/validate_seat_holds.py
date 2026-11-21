#!/usr/bin/env python3
"""Validate assets/data/seat-holds.json (docs/seat-history-design.md, Phase 2).

Tier 1 (exit 1) is scripts/lib/seat_holds.holds_errors: unknown seats, missing or retired
vgIds, an end without a reason from the shared list, 'redistricted' on a seat that was not
redrawn that day, a hold running past its seat's redraw, overlapping holds on one seat or
for one person, suspensions outside their hold, and the append-only check against the
committed (HEAD) copy: a closed hold is never removed or changed.

Tier 2 (printed, never gates): holds with an unknown start, seats with no current holder.

Usage: python scripts/validate_seat_holds.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.seat_holds import holds_errors, report, vacancy_note_errors, vacancy_report  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDS = "assets/data/seat-holds.json"


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def committed(rel):
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO_ROOT,
                             capture_output=True, check=True)
        return json.loads(out.stdout.decode("utf-8"))
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def main():
    doc, seats = load(HOLDS), load("assets/data/seats.json")
    merged = load("assets/data/id-crosswalk-ledger.json").get("merged", {})
    previous = committed(HOLDS)
    corrections = load("assets/data/seat-hold-overrides.json").get("corrections", [])
    errs = holds_errors(doc, seats, merged, previous=previous, corrections=corrections) + vacancy_note_errors(doc, seats)
    if errs:
        print(f"{len(errs)} error(s) in {HOLDS}:", *errs, sep="\n  ")
        return 1
    if previous is None:
        print(f"note: no committed {HOLDS} to compare with; append-only check skipped")
    for line in report(doc, seats) + vacancy_report(doc, seats):
        print(f"note: {line}")
    print(f"{HOLDS} is valid: {doc['metadata']['count']} holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
