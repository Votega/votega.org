"""
update_general_from_runoff.py

Reads the primary runoff results CSV, determines winners per party per contest,
then updates races.json:
  - For races still at activePhase == "runoff":
      * Parties WITH a runoff: promote winner from phases.runoff.ballots
      * Parties WITHOUT a runoff (settled in the primary): promote winner from
        phases.primary.ballots using the primary results CSV, or carry over
        directly if only one primary candidate existed
  - Leaves "primary" and "general" races untouched

Usage: python scripts/update_general_from_runoff.py
"""

import csv
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

BASE          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNOFF_CSV    = os.path.join(BASE, "assets", "data", "ga-primary-runoff-results.csv")
PRIMARY_CSV   = os.path.join(BASE, "assets", "data", "Total Votes Results - OFFICIAL.csv")
RACES_PATH    = os.path.join(BASE, "assets", "data", "races.json")

# ---------------------------------------------------------------------------
# Runoff contest base → race ID (statewide offices only)
# Legislative districts are resolved dynamically via regex (same as primary script)
# ---------------------------------------------------------------------------
RUNOFF_MAP = {
    "US2":  "senate-2026",
    "S1":   "ga-governor-2026",
    "S2":   "ga-lt-governor-2026",
    "S3":   "ga-secretary-of-state-2026",
    "S6":   "ga-insurance-commissioner-2026",
    "S7":   "ga-school-superintendent-2026",
    "S8":   "ga-labor-commissioner-2026",
    "S13":  "ga-psc-5-2026",
}

PARTY_LABEL_MAP = {"REP": "Republican", "DEM": "Democrat"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect_delimiter(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
    return "\t" if sample.count("\t") > sample.count(",") else ","


def normalize_name(name):
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"\(I\)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\"'()]", "", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def names_match(csv_name, json_name):
    cv = set(normalize_name(csv_name).split())
    jn = set(normalize_name(json_name).split())
    if not cv or not jn:
        return False
    overlap = cv & jn
    return len(overlap) >= min(len(cv), len(jn), 2)


def get_contest_base_and_party(contest_id):
    if contest_id.endswith("R"):
        return contest_id[:-1], "Republican"
    if contest_id.endswith("D"):
        return contest_id[:-1], "Democrat"
    return contest_id, None


def get_race_id_for_contest(contest_base):
    if contest_base in RUNOFF_MAP:
        return RUNOFF_MAP[contest_base]
    # U.S. House: USH{n} — district IDs are zero-padded to 2 digits (e.g. ga-01-2026)
    m = re.match(r"^USH(\d+)$", contest_base)
    if m:
        return f"ga-{int(m.group(1)):02d}-2026"
    # State Senate: SSD{n} or SS{n}
    m = re.match(r"^SS[D]?(\d+)$", contest_base)
    if m:
        return f"ga-senate-{m.group(1)}-2026"
    # State House: SHD{n}
    m = re.match(r"^SHD(\d+)$", contest_base)
    if m:
        return f"ga-house-{m.group(1)}-2026"
    return None


def find_matching_candidate(winner_name, candidates):
    for c in candidates:
        if names_match(winner_name, c.get("name", "")):
            return c
    # Last-name fallback
    winner_last = normalize_name(winner_name).split()
    winner_last = winner_last[-1] if winner_last else ""
    for c in candidates:
        parts = normalize_name(c.get("name", "")).split()
        if winner_last and parts and winner_last == parts[-1]:
            return c
    return None


# ---------------------------------------------------------------------------
# CSV parsing — returns { contest_base: { party_label: winner_name } }
# ---------------------------------------------------------------------------

def parse_csv_winners(path):
    delimiter = detect_delimiter(path)
    tallies = {}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 6:
                continue
            _, contest_id, ballot_name, _, party, total_str = row[:6]
            contest_id  = contest_id.strip()
            ballot_name = ballot_name.strip()
            party       = party.strip()
            if not contest_id or ballot_name == "Total Votes":
                continue
            try:
                votes = int(total_str.strip().replace(",", ""))
            except ValueError:
                continue

            if contest_id not in tallies:
                tallies[contest_id] = {}
            if party not in tallies[contest_id]:
                tallies[contest_id][party] = {}
            tallies[contest_id][party][ballot_name] = votes

    winners = {}  # { contest_base: { party_label: winner_name } }
    for contest_id, party_data in tallies.items():
        base, party_label = get_contest_base_and_party(contest_id)
        if party_label is None:
            continue  # skip nonpartisan / special election contests
        raw_party = "REP" if party_label == "Republican" else "DEM"
        candidates_for_party = party_data.get(raw_party, {})
        if candidates_for_party:
            winner_name = max(candidates_for_party, key=candidates_for_party.get)
            if base not in winners:
                winners[base] = {}
            winners[base][party_label] = winner_name

    return winners


# ---------------------------------------------------------------------------
# Main update logic
# ---------------------------------------------------------------------------

def update_races(races_data, runoff_winners, primary_winners):
    updated  = 0
    warnings = []

    race_by_id = {r["id"]: r for r in races_data["races"]}

    # Collect all race IDs referenced by runoff contests
    runoff_race_ids = set()
    for contest_base in runoff_winners:
        rid = get_race_id_for_contest(contest_base)
        if rid:
            runoff_race_ids.add(rid)

    # Process every runoff race, even those with no runoff contest in CSV
    # (their general candidates come entirely from primary winners / single candidates)
    for race in races_data["races"]:
        if race["activePhase"] != "runoff":
            continue

        rid           = race["id"]
        primary_phase = race["phases"].get("primary", {})
        runoff_phase  = race["phases"].get("runoff", {})
        general_phase = race["phases"].setdefault("general", {"electionDate": "2026-11-03"})

        primary_ballots = primary_phase.get("ballots", {})
        runoff_ballots  = runoff_phase.get("ballots", {})

        # Determine all parties we need to place in general
        all_parties = set(primary_ballots.keys()) | set(runoff_ballots.keys())
        if not all_parties:
            warnings.append(f"{rid}: no primary or runoff candidates found — skipping")
            continue

        # Find the reverse-lookup contest base for this race in each CSV
        # so we can look up the winner name
        def contest_base_for_race(winner_dict, target_rid):
            for cb, pw in winner_dict.items():
                if get_race_id_for_contest(cb) == target_rid:
                    return cb
            return None

        runoff_base  = contest_base_for_race(runoff_winners, rid)
        primary_base = contest_base_for_race(primary_winners, rid)

        new_ballots = {}

        for party in sorted(all_parties):
            # --- Does this party have a runoff entry? ---
            party_in_runoff = (runoff_base and
                               party in runoff_winners.get(runoff_base, {}))

            if party_in_runoff:
                winner_name = runoff_winners[runoff_base][party]
                source_candidates = runoff_ballots.get(party, [])
                source_label = "runoff"
            else:
                # Fall back to primary winner
                party_in_primary = (primary_base and
                                    party in primary_winners.get(primary_base, {}))
                if party_in_primary:
                    winner_name = primary_winners[primary_base][party]
                    source_candidates = primary_ballots.get(party, [])
                    source_label = "primary (CSV)"
                else:
                    # No CSV winner — carry over if uncontested, else warn
                    primary_cands = primary_ballots.get(party, [])
                    if len(primary_cands) == 1:
                        new_ballots[party] = [primary_cands[0]]
                        name = primary_cands[0].get("name") or primary_cands[0].get("memberId", "?")
                        print(f"  {rid} / {party}: uncontested primary -> carried over {name}")
                        continue
                    elif len(primary_cands) == 0:
                        # Party had no candidates (e.g. no Dem filed for this race) — skip
                        continue
                    else:
                        warnings.append(
                            f"{rid} / {party}: multiple primary candidates, no CSV match — "
                            f"use set_general_candidates.py to fix manually"
                        )
                        # Create minimal fallback so the race still transitions
                        new_ballots[party] = [{"type": "challenger", "name": f"TBD ({party})", "party": party}]
                        continue

            matched = find_matching_candidate(winner_name, source_candidates)
            if not matched:
                if len(source_candidates) == 1:
                    matched = source_candidates[0]
                    print(f"  {rid} / {party}: sole {source_label} candidate used (name absent)")
                else:
                    warnings.append(
                        f"{rid} / {party}: no name match for '{winner_name}' in {source_label} — fallback created"
                    )
                    matched = {"type": "challenger", "name": winner_name, "party": party}

            new_ballots[party] = [matched]

        if not new_ballots:
            warnings.append(f"{rid}: no candidates resolved — skipping phase flip")
            continue

        general_phase["ballots"] = new_ballots
        general_phase.pop("candidates", None)  # remove legacy empty list if present
        race["activePhase"] = "general"
        updated += 1

    return updated, warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"Parsing runoff CSV:  {RUNOFF_CSV}")
    runoff_winners = parse_csv_winners(RUNOFF_CSV)
    print(f"  Runoff partisan contests: {len(runoff_winners)}")

    print(f"Parsing primary CSV: {PRIMARY_CSV}")
    primary_winners = parse_csv_winners(PRIMARY_CSV)
    print(f"  Primary partisan contests: {len(primary_winners)}")

    with open(RACES_PATH, encoding="utf-8") as f:
        races_data = json.load(f)

    before = sum(1 for r in races_data["races"] if r["activePhase"] == "runoff")
    print(f"\nRaces at 'runoff' before: {before}")

    updated, warnings = update_races(races_data, runoff_winners, primary_winners)

    after = sum(1 for r in races_data["races"] if r["activePhase"] == "runoff")
    print(f"Updated {updated} races to 'general'")
    print(f"Races at 'runoff' after:  {after}")

    if warnings:
        print(f"\nWarnings ({len(warnings)}) — manual fix needed:")
        for w in warnings:
            print(f"  WARN: {w}")
    else:
        print("\nNo warnings — all races resolved cleanly.")

    races_data["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(RACES_PATH, "w", encoding="utf-8") as f:
        json.dump(races_data, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {RACES_PATH}")


if __name__ == "__main__":
    main()
