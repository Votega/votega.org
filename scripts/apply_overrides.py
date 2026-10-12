"""
Apply manual overrides from ga-race-candidate-overrides.json into races.json.

Run this after any programmatic edit to races.json to ensure all manual
overrides (open seat notes, withdrawn/disqualified flags, candidate enrichments)
are reflected in the file.

This is a backstop to build_legislative_races.py, which applies the same
overrides against the *source* export at build time. Because this script runs
over the built races.json, a `remove` override here is normally a no-op (the
duplicate was already dropped upstream) — the removal path is kept only to catch
a duplicate re-introduced by a hand edit. See CODEBASE-REVIEW-2026-08-18.md
findings 5.2, 5.3, 5.4.

Usage:
    python scripts/apply_overrides.py            # apply and write
    python scripts/apply_overrides.py --check    # exit 1 if races.json is behind

--check is what .github/workflows/apply-race-candidate-overrides.yml runs on a
pull request; on a push to main the same workflow applies and commits instead.
"""
import copy
import json
import sys
from pathlib import Path

from lib.atomic_io import write_json_atomic

RACES     = Path("assets/data/races.json")
OVERRIDES = Path("assets/data/ga-race-candidate-overrides.json")


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    write_json_atomic(path, data, indent=2)


# --- Name matching (mirrors build_legislative_races.py; keep the two in sync) ---
# `remove` overrides target a *positional* candidate id (a row index into the
# source export), so a re-ordered or shortened source makes the id point at a
# different person. Verify the recorded `_name` before deleting anyone.

def override_target_name(patch: dict) -> str:
    """The candidate name a `remove` override says it targets. `_name` is written
    as e.g. 'Brian Lamar Prince (duplicate of d-1)' — strip the parenthetical."""
    name = (patch.get("_name") or "").split("(")[0].strip()
    return name


def names_match(a: str, b: str) -> bool:
    """True if a and b likely name the same person: last name plus first name or
    first initial."""
    an, bn = a.lower().split(), b.lower().split()
    if not an or not bn:
        return False
    if an[-1] != bn[-1]:
        return False
    return an[0] == bn[0] or an[0][0] == bn[0][0]


def phase_candidate_lists(phase_data: dict):
    """Yield every mutable candidate list on a phase. races.json has two shapes —
    `ballots` (party -> [candidates]) and a flat `candidates` array — and 184 of
    717 phases use the flat one. Walking only `ballots` silently skipped every
    override on a judicial/PSC race. See finding 5.3."""
    for cands in phase_data.get("ballots", {}).values():
        yield cands
    flat = phase_data.get("candidates")
    if isinstance(flat, list):
        yield flat


def apply(races_data: dict, overrides: dict, verbose: bool = True):
    """Apply race and candidate overrides. Returns a stats dict."""

    race_patches = {
        k: v for k, v in overrides.get("_raceOverrides", {}).items()
        if not k.startswith("_")
    }
    cand_patches = {
        k: v for k, v in overrides.items()
        if not k.startswith("_")
    }

    stats = {"races": 0, "removed": 0, "patched": 0}
    matched_keys = set()          # candidate-override keys that hit a live candidate
    mismatches = []               # (id, expected_name, actual_name) — remove aborted

    for race in races_data.get("races", []):
        race_id = race.get("id", "")

        patch = race_patches.get(race_id)
        if patch:
            for k, v in patch.items():
                race[k] = v
            if verbose:
                print(f"  Race {race_id}: {list(patch.keys())}")
            stats["races"] += 1

        for phase_data in race.get("phases", {}).values():
            for cands in phase_candidate_lists(phase_data):
                to_remove = []
                for c in cands:
                    if not isinstance(c, dict):
                        continue
                    cid = c.get("id")
                    if not cid:
                        continue
                    patch = cand_patches.get(cid)
                    if not patch:
                        continue
                    matched_keys.add(cid)

                    if patch.get("remove"):
                        expected = override_target_name(patch)
                        if expected and not names_match(expected, c.get("name", "")):
                            # The positional id now points at someone else — do
                            # not delete on a guess. Keep them and report loudly.
                            mismatches.append((cid, expected, c.get("name", "")))
                            continue
                        to_remove.append(c)
                        if verbose:
                            print(f"    Candidate {cid}: [removed]")
                        stats["removed"] += 1
                    else:
                        for k, v in patch.items():
                            if not k.startswith("_"):
                                c[k] = v
                        applied = [k for k in patch if not k.startswith("_")]
                        if verbose:
                            print(f"    Candidate {cid}: {applied}")
                        stats["patched"] += 1

                for c in to_remove:
                    cands.remove(c)

    # Unmatched keys — previously a silent no-op, which hid both a mis-keyed
    # override (5.4) and a stale positional id. Split by kind: a `remove` key
    # that matches nothing here is expected (build_legislative_races already
    # dropped it upstream); a *patch* key that matches nothing is a real problem.
    unmatched = set(cand_patches) - matched_keys
    unmatched_removes = {k for k in unmatched if cand_patches[k].get("remove")}
    unmatched_patches = unmatched - unmatched_removes

    if unmatched_removes and verbose:
        print(f"\n  note: {len(unmatched_removes)} 'remove' override(s) matched no "
              f"candidate here (expected — applied upstream in build_legislative_races).")
    if unmatched_patches and verbose:
        print(f"\nWARNING: {len(unmatched_patches)} candidate override(s) target an id "
              f"that no candidate has — these do nothing:", file=sys.stderr)
        for k in sorted(unmatched_patches):
            nm = cand_patches[k].get("_name") or "?"
            print(f"  {k}  (_name: {nm})", file=sys.stderr)

    stats["mismatches"] = mismatches
    stats["unmatched_patches"] = sorted(unmatched_patches)
    return stats


def candidate_index(races_data: dict) -> dict:
    """{(race id, phase, candidate id): candidate} across both ballot shapes."""
    out = {}
    for race in races_data.get("races", []):
        rid = race.get("id")
        for phase_name, phase_data in (race.get("phases") or {}).items():
            for cands in phase_candidate_lists(phase_data):
                for c in cands:
                    if isinstance(c, dict) and c.get("id"):
                        out[(rid, phase_name, c["id"])] = c
    return out


def drifted(before: dict, after: dict) -> list:
    """Human-readable list of what applying the overrides would change.

    Empty means races.json already reflects every override. This is the whole
    point of --check: the override file is the authored source, races.json is
    what the site serves, and nothing but this script connects them -- so they
    can drift apart silently, which is exactly what happened on 2026-10-11 when
    27 curated candidate profiles sat in the override file for a day without
    reaching the site."""
    out = []

    before_races = {r.get("id"): r for r in before.get("races", [])}
    for race in after.get("races", []):
        rid = race.get("id")
        prev = before_races.get(rid)
        if prev is None:
            continue
        for key, value in race.items():
            if key != "phases" and prev.get(key) != value:
                out.append(f"{rid}: race field {key!r} would change")

    before_c, after_c = candidate_index(before), candidate_index(after)
    for key in sorted(set(before_c) - set(after_c)):
        out.append(f"{key[0]} [{key[1]}]: {key[2]} would be removed")
    for key in sorted(set(after_c) & set(before_c)):
        b, a = before_c[key], after_c[key]
        fields = sorted(f for f in set(b) | set(a) if b.get(f) != a.get(f))
        if fields:
            out.append(f"{key[0]} [{key[1]}]: {key[2]} -> {', '.join(fields)}")
    return out


def run_check(races_data: dict, overrides: dict) -> int:
    """Report whether races.json already reflects the overrides. Exit 1 if not."""
    before = copy.deepcopy(races_data)
    stats = apply(races_data, overrides, verbose=False)

    if stats["mismatches"]:
        print("ERROR: 'remove' override(s) point at a different candidate than "
              "their _name:", file=sys.stderr)
        for cid, expected, actual in stats["mismatches"]:
            print(f"  {cid}: expected {expected!r}, found {actual!r}", file=sys.stderr)
        return 1

    changes = drifted(before, races_data)
    if changes:
        print(f"::error::{RACES} does not reflect {OVERRIDES} — "
              f"{len(changes)} pending change(s). Run: python scripts/apply_overrides.py",
              file=sys.stderr)
        for line in changes:
            print(f"  {line}", file=sys.stderr)
        return 1

    # Unmatched patch keys are reported but do NOT fail the check: they are a
    # data-hygiene problem (an override nobody will ever see), not a drift
    # between the two files, and failing on them would wedge CI on a pre-existing
    # stale key rather than on the thing this check exists to catch.
    if stats["unmatched_patches"]:
        print(f"note: {len(stats['unmatched_patches'])} override(s) target an id no "
              f"candidate has — they do nothing:")
        for k in stats["unmatched_patches"]:
            print(f"  {k}")

    print(f"{RACES} is up to date with {OVERRIDES}.")
    return 0


def main():
    check = "--check" in sys.argv

    races_data = load_json(RACES)
    overrides = load_json(OVERRIDES)

    if check:
        sys.exit(run_check(races_data, overrides))

    print(f"Loaded {RACES} and {OVERRIDES}")
    print("Applying overrides:")
    stats = apply(races_data, overrides)

    if stats["mismatches"]:
        print("\nERROR: 'remove' override(s) point at a different candidate than "
              "their _name — refusing to delete the wrong person:", file=sys.stderr)
        for cid, expected, actual in stats["mismatches"]:
            print(f"  {cid}: expected {expected!r}, found {actual!r}", file=sys.stderr)
        sys.exit(1)

    save_json(RACES, races_data)
    print(f"\nDone — {stats['races']} race(s), "
          f"{stats['patched']} patched, {stats['removed']} removed.")


if __name__ == "__main__":
    main()
