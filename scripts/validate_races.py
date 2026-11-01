#!/usr/bin/env python3
"""Validate assets/data/races.json on the push path, before anything publishes it.

races.json is the core of the elections section and has four push-triggered
consumers (the public ga-races-elections publish, the ballot-preview and
unopposed-count refreshes, the updatedAt stamp). lib/races_guard.py protects only
the scripts that mutate it; a hand edit in tools/race-candidate-editor.html, or a
merge, reaches those consumers with nothing checking it beyond "valid JSON".

Two kinds of check, both stdlib-only:

  absolute  The file contradicts itself. Always runs, whatever the trigger.
            Unique race ids, an activePhase that exists and has candidates, unique
            candidate ids per phase, a recorded winner that points at someone on
            that race's ballot.

  change    What a push did to the file, against --base (the pre-push commit).
            Only runs when a readable baseline exists. A race added or dropped, a
            candidate total that fell sharply, a phase that moved anywhere but
            forward, a recorded winner that was replaced or removed.

A deliberate structural change (adding or removing a race, moving a phase back,
changing a recorded winner) is allowed by putting `[races-structure-change]` in
the message of a commit in the pushed range. The marker relaxes the change checks
only; the absolute checks always apply.

Usage:
  python scripts/validate_races.py                      # absolute checks only
  python scripts/validate_races.py --base <sha>         # plus the change checks
  python scripts/validate_races.py --file path --base-file old.json   # for tests
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.races_guard import (  # noqa: E731
    RacesGuardError, assert_phase_transitions, assert_race_set_preserved, phase_candidates,
)

RACES_PATH = "assets/data/races.json"
MARKER = "[races-structure-change]"
ZERO_SHA = "0" * 40

# Phases only move forward through an election. Anything else is a likely slip.
ALLOWED_TRANSITIONS = {("primary", "runoff"), ("primary", "general"), ("runoff", "general")}

# Candidates come off a ballot a few at a time (withdrawals, off-ballot cleanups).
# A bigger single-push drop is a damaged file, not an edit.
MAX_CANDIDATE_DROP = 0.05


def _races(doc):
    r = doc.get("races") if isinstance(doc, dict) else None
    return r if isinstance(r, list) else []


def _active_size(race):
    phase = (race.get("phases") or {}).get(race.get("activePhase"))
    return sum(1 for _ in phase_candidates(phase))


# --------------------------------------------------------------------------- #
# absolute checks
# --------------------------------------------------------------------------- #
def check_document(doc):
    """Return a list of problems that make the file contradict itself."""
    errs = []
    if not isinstance(doc, dict):
        return ["races.json is not a JSON object"]
    if not isinstance(doc.get("races"), list) or not doc["races"]:
        return ["races.json has no 'races' list (or it is empty)"]
    if not isinstance(doc.get("updatedAt"), str):
        errs.append("top-level 'updatedAt' is missing")

    seen = set()
    for i, race in enumerate(doc["races"]):
        rid = race.get("id") if isinstance(race, dict) else None
        if not rid:
            errs.append(f"races[{i}] has no id")
            continue
        if rid in seen:
            errs.append(f"{rid}: duplicate race id")
        seen.add(rid)

        phases = race.get("phases")
        if not isinstance(phases, dict) or not phases:
            errs.append(f"{rid}: no phases")
            continue
        active = race.get("activePhase")
        if active not in phases:
            errs.append(f"{rid}: activePhase {active!r} is not one of its phases {sorted(phases)}")
        elif _active_size(race) == 0:
            errs.append(f"{rid}: active phase {active!r} has no candidates")

        all_ids = set()
        for name, phase in phases.items():
            ids = [c.get("id") for c in phase_candidates(phase) if c.get("id")]
            dupes = sorted({x for x in ids if ids.count(x) > 1})
            if dupes:
                errs.append(f"{rid}/{name}: duplicate candidate id(s) {dupes[:5]}")
            all_ids.update(ids)

        status, winner = race.get("status"), race.get("winner")
        if winner is not None:
            if status != "certified":
                errs.append(f"{rid}: has a winner but status is {status!r}, not 'certified'")
            if not isinstance(winner, dict):
                errs.append(f"{rid}: winner is not an object")
            else:
                cid, mid = winner.get("candidateId"), winner.get("memberId")
                if not cid and not mid:
                    errs.append(f"{rid}: winner names neither a candidateId nor a memberId")
                elif cid and cid not in all_ids:
                    errs.append(f"{rid}: winner.candidateId {cid!r} is not on any ballot in the race")
        elif status == "certified":
            errs.append(f"{rid}: status is 'certified' but no winner is recorded")
    return errs


# --------------------------------------------------------------------------- #
# change checks
# --------------------------------------------------------------------------- #
def check_change(before, after, allow_structure_change=False):
    """Return a list of problems with how `after` differs from `before`."""
    if allow_structure_change:
        return []
    errs = []
    try:
        assert_race_set_preserved(before, after)
        assert_phase_transitions(before, after, allowed=ALLOWED_TRANSITIONS)
    except RacesGuardError as exc:
        errs.append(str(exc))
        return errs  # the rest of the comparison assumes the same race set

    b = {r["id"]: r for r in _races(before)}
    a = {r["id"]: r for r in _races(after)}

    nb = sum(_active_size(r) for r in b.values())
    na = sum(_active_size(r) for r in a.values())
    if nb and na < nb * (1 - MAX_CANDIDATE_DROP):
        errs.append(f"active-ballot candidates fell {nb} -> {na} "
                    f"(more than {int(MAX_CANDIDATE_DROP * 100)}% in one push)")

    for rid, rb in b.items():
        wb, wa = rb.get("winner"), a[rid].get("winner")
        if wb is not None and wb != wa:
            errs.append(f"{rid}: recorded winner was "
                        f"{'removed' if wa is None else 'replaced'}")
    return errs


# --------------------------------------------------------------------------- #
# baseline from git
# --------------------------------------------------------------------------- #
def _git(*args):
    return subprocess.run(["git", *args], capture_output=True)


def load_base(base):
    """(baseline document or None, note). None means the change checks cannot run."""
    if not base or base == ZERO_SHA:
        return None, "no baseline commit (new branch or manual run); change checks skipped"
    r = _git("show", f"{base}:{RACES_PATH}")
    if r.returncode != 0:
        return None, f"baseline {base[:10]} is not readable here; change checks skipped"
    try:
        return json.loads(r.stdout.decode("utf-8")), ""
    except ValueError:
        return None, f"baseline {base[:10]} is not valid JSON; change checks skipped"


def marker_in_range(base):
    if not base or base == ZERO_SHA:
        return False
    r = _git("log", "--format=%B", f"{base}..HEAD")
    return r.returncode == 0 and MARKER in r.stdout.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", default=RACES_PATH)
    ap.add_argument("--base", help="commit to compare against (the pre-push sha)")
    ap.add_argument("--base-file", help="baseline JSON file (instead of --base)")
    args = ap.parse_args(argv)

    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"::error::cannot read {args.file}: {exc}")
        return 1

    problems = [("file", e) for e in check_document(doc)]

    if args.base_file:
        with open(args.base_file, encoding="utf-8") as fh:
            before, note, allow = json.load(fh), "", False
    else:
        before, note = load_base(args.base)
        allow = marker_in_range(args.base)
    if before is None:
        print(f"validate_races: {note}")
    elif allow:
        print(f"validate_races: {MARKER} found in the pushed commits; change checks skipped")
    else:
        problems += [("change", e) for e in check_change(before, doc)]

    if problems:
        for kind, e in problems:
            print(f"::error title=races.json {kind} check::{e}")
        print(f"\nvalidate_races: {len(problems)} problem(s). If a structural change is "
              f"intended, put {MARKER} in the commit message.")
        return 1
    print(f"validate_races: ok ({len(_races(doc))} races)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
