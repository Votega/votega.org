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
    python scripts/apply_overrides.py
"""
import json
import sys
from pathlib import Path

RACES     = Path("assets/data/races.json")
OVERRIDES = Path("assets/data/ga-race-candidate-overrides.json")


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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


def apply(races_data: dict, overrides: dict):
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
                        print(f"    Candidate {cid}: [removed]")
                        stats["removed"] += 1
                    else:
                        for k, v in patch.items():
                            if not k.startswith("_"):
                                c[k] = v
                        applied = [k for k in patch if not k.startswith("_")]
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

    if unmatched_removes:
        print(f"\n  note: {len(unmatched_removes)} 'remove' override(s) matched no "
              f"candidate here (expected — applied upstream in build_legislative_races).")
    if unmatched_patches:
        print(f"\nWARNING: {len(unmatched_patches)} candidate override(s) target an id "
              f"that no candidate has — these do nothing:", file=sys.stderr)
        for k in sorted(unmatched_patches):
            nm = cand_patches[k].get("_name") or "?"
            print(f"  {k}  (_name: {nm})", file=sys.stderr)

    stats["mismatches"] = mismatches
    stats["unmatched_patches"] = sorted(unmatched_patches)
    return stats


def main():
    print(f"Loading {RACES} ...")
    races_data = load_json(RACES)

    print(f"Loading {OVERRIDES} ...")
    overrides = load_json(OVERRIDES)

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
