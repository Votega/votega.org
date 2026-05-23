"""
fix_general_fallbacks.py

Targeted patch: replaces the minimal fallback general-ballot/candidate entries
that were created by update_general_from_primary.py when name matching failed.
Each fix copies the proper candidate object from primary.ballots into general.ballots
(or general.candidates for judicial races).

Run once after update_general_from_primary.py.
"""

import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_PATH = os.path.join(BASE, "assets", "data", "races.json")


def fix(races_data):
    race_by_id = {r["id"]: r for r in races_data["races"]}
    fixes_applied = 0

    def copy_primary_to_general_partisan(race_id, party):
        """Copy first (or only) candidate from primary.ballots[party] to general.ballots[party]."""
        nonlocal fixes_applied
        race = race_by_id.get(race_id)
        if not race:
            print(f"  WARN: race not found: {race_id}")
            return
        src = race["phases"]["primary"].get("ballots", {}).get(party, [])
        if not src:
            print(f"  WARN: no primary {party} candidates in {race_id}")
            return
        # Use the first/only candidate (uncontested incumbent or intended winner)
        candidate = src[0]
        race["phases"]["general"]["ballots"][party] = [candidate]
        name = candidate.get("name") or candidate.get("memberId", "(memberId only)")
        print(f"  Fixed {race_id} / {party}: {name}")
        fixes_applied += 1

    def copy_named_primary_to_general_partisan(race_id, party, primary_index=0):
        """Copy a specific index from primary.ballots[party] to general.ballots[party]."""
        nonlocal fixes_applied
        race = race_by_id.get(race_id)
        if not race:
            print(f"  WARN: race not found: {race_id}")
            return
        src = race["phases"]["primary"].get("ballots", {}).get(party, [])
        if primary_index >= len(src):
            print(f"  WARN: index {primary_index} out of range for {race_id} / {party}")
            return
        candidate = src[primary_index]
        race["phases"]["general"]["ballots"][party] = [candidate]
        print(f"  Fixed {race_id} / {party}: {candidate.get('name', '?')}")
        fixes_applied += 1

    def copy_primary_to_general_judicial(race_id, primary_index=0):
        """Copy a specific primary candidate to general.candidates."""
        nonlocal fixes_applied
        race = race_by_id.get(race_id)
        if not race:
            print(f"  WARN: race not found: {race_id}")
            return
        src = race["phases"]["primary"].get("candidates", [])
        if primary_index >= len(src):
            print(f"  WARN: index {primary_index} out of range for {race_id}")
            return
        candidate = src[primary_index]
        race["phases"]["general"]["candidates"] = [candidate]
        print(f"  Fixed {race_id}: {candidate.get('name', '?')}")
        fixes_applied += 1

    # -------------------------------------------------------------------------
    # Federal incumbents stored as memberId-only in primary.ballots
    # -------------------------------------------------------------------------
    print("Federal incumbents:")
    copy_primary_to_general_partisan("ga-02-2026", "Democrat")   # B000490 Sanford Bishop
    copy_primary_to_general_partisan("ga-03-2026", "Republican") # J000311 Brian Jack
    copy_primary_to_general_partisan("ga-04-2026", "Democrat")   # J000288 Hank Johnson
    copy_primary_to_general_partisan("ga-05-2026", "Democrat")   # W000788 Nikema Williams
    copy_primary_to_general_partisan("ga-06-2026", "Democrat")   # M001208 Lucy McBath
    copy_primary_to_general_partisan("ga-08-2026", "Republican") # S001189 Austin Scott
    copy_primary_to_general_partisan("ga-09-2026", "Republican") # C001116 Andrew Clyde

    # -------------------------------------------------------------------------
    # GA state incumbents/challengers where CSV nickname ≠ legal name in JSON
    # -------------------------------------------------------------------------
    print("\nGA state name mismatches:")
    # ga-house-16 Rep: "Trey Kelley (I)" → "Othel Doyle Kelley Iii"
    copy_primary_to_general_partisan("ga-house-16-2026", "Republican")
    # ga-house-65 Rep: "Gordon W. Rolle, Jr." → "Gordon Washington Rolle Jr"
    copy_primary_to_general_partisan("ga-house-65-2026", "Republican")
    # ga-house-74 Dem: "Robert Flournoy, Jr. (I)" → "Robert Flournoy Jr"
    copy_primary_to_general_partisan("ga-house-74-2026", "Democrat")
    # ga-house-104 Rep: "Chuck Efstration (I)" → "Charles Paul Efstration Iii"
    copy_primary_to_general_partisan("ga-house-104-2026", "Republican")
    # ga-house-124 Rep: "Trey Rhodes (I)" → "Ralph Lanier Rhodes Iii"
    copy_primary_to_general_partisan("ga-house-124-2026", "Republican")
    # ga-house-126 Dem: "L.C. Myles Jr. (I)" → "L C Myles Jr"
    copy_primary_to_general_partisan("ga-house-126-2026", "Democrat")
    # ga-house-148 Rep: "Noel W. Williams, Jr. (I)" → "Noel Warren Williams Jr"
    copy_primary_to_general_partisan("ga-house-148-2026", "Republican")
    # ga-house-161 Rep: "Bill Hitchens (I)" → "William W Hitchens Jr"
    copy_primary_to_general_partisan("ga-house-161-2026", "Republican")
    # ga-senate-39 Rep: "John F. Guest, Jr." → "John Franklin Guest Jr"
    copy_primary_to_general_partisan("ga-senate-39-2026", "Republican")

    # -------------------------------------------------------------------------
    # New challengers where CSV short name ≠ full legal name in JSON
    # -------------------------------------------------------------------------
    print("\nNew challengers:")
    # ga-house-27 Dem: "Jay Kirkland" → "Joseph Ivey Kirkland Iv"
    copy_primary_to_general_partisan("ga-house-27-2026", "Democrat")
    # ga-house-108 Rep: "Elvia Davila" → "Elvia Davila-Pelayo"
    copy_primary_to_general_partisan("ga-house-108-2026", "Republican")
    # ga-house-167 Dem: "Nathaniel Hicks, Jr." → "Nathaniel Hicks Jr"
    copy_primary_to_general_partisan("ga-house-167-2026", "Democrat")

    # -------------------------------------------------------------------------
    # Judicial: nickname / shortened name didn't match legal name
    # -------------------------------------------------------------------------
    print("\nJudicial:")
    # alapaha-perryman: "Dick Perryman (I)" → "Richard Lowery Perryman III"
    copy_primary_to_general_judicial("superior-court-alapaha-perryman-2026", 0)
    # atlanta-eaton: "Chuck Eaton (I)" → "Charles M. Eaton Jr." (has website)
    copy_primary_to_general_judicial("superior-court-atlanta-eaton-2026", 0)
    # clayton-mason: Deitra Butler (index 1) defeated incumbent Mason (index 0)
    copy_primary_to_general_judicial("superior-court-clayton-mason-2026", 1)
    # tifton-reinhardt: "Bill Reinhardt (I)" → "William D. Reinhardt II"
    copy_primary_to_general_judicial("superior-court-tifton-reinhardt-2026", 0)

    print(f"\nTotal fixes applied: {fixes_applied}")
    return fixes_applied


def main():
    with open(RACES_PATH, encoding="utf-8") as f:
        races_data = json.load(f)

    fixes = fix(races_data)

    with open(RACES_PATH, "w", encoding="utf-8") as f:
        json.dump(races_data, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {RACES_PATH}")


if __name__ == "__main__":
    main()
