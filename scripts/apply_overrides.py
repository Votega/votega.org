"""
Apply manual overrides from ga-race-candidate-overrides.json into races.json.

Run this after any programmatic edit to races.json to ensure all manual
overrides (open seat notes, withdrawn/disqualified flags, candidate enrichments)
are reflected in the file.

Usage:
    python scripts/apply_overrides.py
"""
import json
from pathlib import Path

RACES     = Path("assets/data/races.json")
OVERRIDES = Path("assets/data/ga-race-candidate-overrides.json")


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def apply(races_data: dict, overrides: dict) -> tuple[int, int]:
    """Apply race and candidate overrides. Returns (race_count, candidate_count)."""

    # Race-level overrides — keys in _raceOverrides block, excluding metadata
    race_patches = {
        k: v for k, v in overrides.get("_raceOverrides", {}).items()
        if not k.startswith("_")
    }

    # Candidate-level overrides — top-level keys, excluding metadata blocks
    cand_patches = {
        k: v for k, v in overrides.items()
        if not k.startswith("_")
    }

    race_count = 0
    cand_count = 0

    for race in races_data.get("races", []):
        race_id = race.get("id", "")

        patch = race_patches.get(race_id)
        if patch:
            for k, v in patch.items():
                race[k] = v
            print(f"  Race {race_id}: {list(patch.keys())}")
            race_count += 1

        for cands in race.get("phases", {}).get("primary", {}).get("ballots", {}).values():
            for c in cands:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if not cid:
                    continue
                patch = cand_patches.get(cid)
                if patch:
                    for k, v in patch.items():
                        if not k.startswith("_"):
                            c[k] = v
                    applied = [k for k in patch if not k.startswith("_")]
                    print(f"    Candidate {cid}: {applied}")
                    cand_count += 1

    return race_count, cand_count


def main():
    print(f"Loading {RACES} ...")
    races_data = load_json(RACES)

    print(f"Loading {OVERRIDES} ...")
    overrides = load_json(OVERRIDES)

    print("Applying overrides:")
    race_count, cand_count = apply(races_data, overrides)

    save_json(RACES, races_data)
    print(f"\nDone — {race_count} race(s), {cand_count} candidate(s) patched.")


if __name__ == "__main__":
    main()
