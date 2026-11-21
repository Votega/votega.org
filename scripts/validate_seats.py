#!/usr/bin/env python3
"""Validate assets/data/seats.json, the seat registry (docs/seat-history-design.md, Phase 1).

Tier 1 (exit 1) is scripts/lib/seat_registry.registry_errors: the file contradicting
itself or its inputs (duplicate or malformed ids, a seat on an unknown map, a "redrawn"
seat its next map actually carried over, the seats in force not being exactly
districts 1..N, the statewide seats drifting from ga-executive-seats.json), plus the
append-only check against the committed (HEAD) copy: a published seat is never
removed and its body, district and map never change.

Tier 2 (printed, never gates): seats added since HEAD.

Usage: python scripts/validate_seats.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.seat_registry import registry_errors  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEATS = "assets/data/seats.json"
PLANS = "scripts/data/seat-plans.json"
COMPARISON = "scripts/data/seat-plan-comparison.json"
EXECUTIVE = "assets/data/ga-executive-seats.json"


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def committed(rel):
    """The HEAD copy of `rel`, or None (new file, or not a git checkout)."""
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO_ROOT,
                             capture_output=True, check=True)
        return json.loads(out.stdout.decode("utf-8"))
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def main():
    reg = load(SEATS)
    previous = committed(SEATS)
    errs = registry_errors(reg, load(PLANS), load(COMPARISON)["plans"],
                           load(EXECUTIVE)["seats"], previous=previous)
    if errs:
        print(f"{len(errs)} error(s) in {SEATS}:", *errs, sep="\n  ")
        return 1
    if previous is None:
        print(f"note: no committed {SEATS} to compare with; append-only check skipped")
    else:
        added = sorted({s["id"] for s in reg["seats"]} - {s["id"] for s in previous["seats"]})
        if added:
            print(f"{len(added)} seat(s) added since HEAD: {', '.join(added[:20])}"
                  + (" ..." if len(added) > 20 else ""))
    print(f"{SEATS} is valid: {reg['metadata']['count']} seats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
