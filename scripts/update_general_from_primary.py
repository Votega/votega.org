"""
update_general_from_primary.py

Reads primary results CSV, determines winners per party per contest,
then updates races.json:
  - For races still at activePhase == "primary": set to "general" and populate general ballots/candidates with winners
  - Leaves "runoff" and "general" races untouched
"""

import csv
import json
import os
import re
import unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, "assets", "data", "Total Votes - 2026.05.23_8am.csv")
RACES_PATH = os.path.join(BASE, "assets", "data", "races.json")

# ---------------------------------------------------------------------------
# Contest ID → race ID mapping
# ---------------------------------------------------------------------------

# Partisan legislative / executive races: contest_base → race_id
# contest_base strips the trailing R/D party suffix
PARTISAN_MAP = {
    "USH2":  "ga-02-2026",
    "USH3":  "ga-03-2026",
    "USH4":  "ga-04-2026",
    "USH5":  "ga-05-2026",
    "USH6":  "ga-06-2026",
    "USH7":  "ga-07-2026",
    "USH8":  "ga-08-2026",
    "USH9":  "ga-09-2026",
    "USH10": "ga-10-2026",
    "USH11": "ga-11-2026",
    "USH12": "ga-12-2026",
    "USH13": "ga-13-2026",
    "USH14": "ga-14-2026",
    "S5":    "ga-agriculture-commissioner-2026",
    "S7":    "ga-school-superintendent-2026",
    "S11":   "ga-psc-3-2026",
}

# State Senate: SSD{n}R/D or SS{n}R/D → ga-senate-{n}-2026
# State House: SHD{n}R/D → ga-house-{n}-2026
# These are built dynamically below.

# Nonpartisan judicial contests: contest_id → race_id
JUDICIAL_MAP = {
    "SSC1":   "supreme-court-bethel-2026",
    "SSC3":   "supreme-court-warren-2026",
    "SCA1":   "court-of-appeals-brown-2026",
    "SCA2":   "court-of-appeals-doyle-2026",
    "SCA3":   "court-of-appeals-gobeil-2026",
    "SCA4":   "court-of-appeals-markle-2026",
    "SCA5":   "court-of-appeals-padgett-2026",
    # Superior Courts
    "SJC1":   "superior-court-alapaha-perryman-2026",
    "SJC2":   "superior-court-alcovy-mccamy-2026",
    "SJC3":   "superior-court-alcovy-zon-2026",
    "SJC4":   "superior-court-appalachian-priest-2026",
    "SJC5":   "superior-court-appalachian-sosebee-2026",
    "SCJ6":   "superior-court-atlanta-benton-2026",
    "SCJ7":   "superior-court-atlanta-eaton-2026",
    "SCJ8":   "superior-court-atlanta-ellerbe-2026",
    "SCJ9":   "superior-court-atlanta-farmer-2026",
    "SCJ10":  "superior-court-atlanta-mcburney-2026",
    "SCJ11":  "superior-court-atlanta-schwall-2026",
    "SCJ12":  "superior-court-atlanta-whitaker-2026",
    "SJC13":  "superior-court-atlantic-hendrix-2026",
    "SJC14":  "superior-court-atlantic-stewart-2026",
    "SJC15":  "superior-court-augusta-heath-2026",
    "SJC16":  "superior-court-augusta-stone-2026",
    "SJC17":  "superior-court-augusta-wright-2026",
    "SJC18":  "superior-court-bell-forsyth-bagley-2026",
    "SJC19":  "superior-court-bell-forsyth-smith-2026",
    "SJC20":  "superior-court-blue-ridge-baker-2026",
    "SJC21":  "superior-court-brunswick-lane-2026",
    "SJC22":  "superior-court-chattahoochee-burch-2026",
    "SJC23":  "superior-court-cherokee-greene-2026",
    "SJC24":  "superior-court-cherokee-patel-2026",
    "SJC25":  "superior-court-cherokee-smith-2026",
    "SJC26":  "superior-court-clayton-carter-2026",
    "SJC27":  "superior-court-clayton-mason-2026",
    "SJC28":  "superior-court-cobb-brown-2026",
    "SJC29":  "superior-court-cobb-harris-2026",
    "SJC30":  "superior-court-cobb-leonard-2026",
    "SJC31":  "superior-court-columbia-blanchard-2026",
    "SJC32":  "superior-court-columbia-fleming-2026",
    "SJC33":  "superior-court-conasauga-morris-2026",
    "SJC34":  "superior-court-conasauga-wilbanks-2026",
    "SJC35":  "superior-court-coweta-bendinger-2026",
    "SJC129": "superior-court-dekalb-jackson-asha-2026",
    "SJC130": "superior-court-dekalb-jackson-latisha-2026",
    "SJC131": "superior-court-dekalb-johnson-2026",
    "SJC39":  "superior-court-dougherty-dent-2026",
    "SJC40":  "superior-court-douglas-adams-2026",
    "SJC41":  "superior-court-eastern-karpf-2026",
    "SJC42":  "superior-court-eastern-stokes-2026",
    "SJC43":  "superior-court-eastern-walmsley-2026",
    "SJC44":  "superior-court-enotah-george-2026",
    "SJC45":  "superior-court-enotah-levins-2026",
    "SJC46":  "superior-court-flint-lewis-2026",
    "SJC47":  "superior-court-flint-palmer-2026",
    "SJC48":  "superior-court-griffin-coker-2026",
    "SJC49":  "superior-court-griffin-kreuziger-2026",
    "SJC50":  "superior-court-griffin-miller-2026",
    "SJC51":  "superior-court-gwinnett-cason-2026",
    "SJC52":  "superior-court-gwinnett-duncan-2026",
    "SJC53":  "superior-court-gwinnett-hamil-2026",
    "SJC54":  "superior-court-gwinnett-hutchinson-2026",
    "SJC55":  "superior-court-gwinnett-mason-2026",
    "SJC56":  "superior-court-houston-smith-2026",
    "SJC57":  "superior-court-lookout-mountain-thompson-2026",
    "SJC58":  "superior-court-macon-mincey-2026",
    "SJC59":  "superior-court-macon-raymond-2026",
    "SJC60":  "superior-court-macon-smith-2026",
    "SJC61":  "superior-court-macon-williford-2026",
    "SJC62":  "superior-court-middle-reeves-2026",
    "SJC63":  "superior-court-middle-smith-2026",
    "SJC64":  "superior-court-mountain-carswell-2026",
    "SJC65":  "superior-court-mountain-jones-2026",
    "SJC66":  "superior-court-northeastern-burton-2026",
    "SJC67":  "superior-court-northeastern-deal-2026",
    "SJC68":  "superior-court-pataula-balkcom-2026",
    "SJC69":  "superior-court-paulding-rollins-2026",
    "SJC70":  "superior-court-piedmont-griffie-2026",
    "SJC71":  "superior-court-rockdale-bills-2026",
    "SJC72":  "superior-court-rome-king-2026",
    "SJC73":  "superior-court-rome-sparks-2026",
    "SJC75":  "superior-court-southern-prine-2026",
    "SJC76":  "superior-court-southern-smith-2026",
    "SJC77":  "superior-court-southern-voyles-2026",
    "SJC78":  "superior-court-southwestern-sizemore-2026",
    "SJC79":  "superior-court-tifton-powell-2026",
    "SJC80":  "superior-court-tifton-reinhardt-2026",
    "SJC81":  "superior-court-towaliga-wilson-2026",
    "SJC82":  "superior-court-waycross-kight-2026",
    "SJC83":  "superior-court-west-georgia-hightower-2026",
    "SJC84":  "superior-court-western-lott-2026",
    "SJC85":  "superior-court-western-norris-2026",
}

PARTY_LABEL_MAP = {"REP": "Republican", "DEM": "Democrat"}


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation for fuzzy matching."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"\(I\)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\"'()]", "", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def name_words(name: str) -> set:
    return set(normalize_name(name).split())


def names_match(csv_name: str, json_name: str) -> bool:
    """Return True if the two names refer to the same person."""
    cv = name_words(csv_name)
    jn = name_words(json_name)
    if not cv or not jn:
        return False
    # If all significant words from one appear in the other
    overlap = cv & jn
    return len(overlap) >= min(len(cv), len(jn), 2)


def get_contest_base_and_party(contest_id: str):
    """Split 'USH10R' → ('USH10', 'Republican') or ('USH10', None) for nonpartisan."""
    if contest_id.endswith("R"):
        return contest_id[:-1], "Republican"
    if contest_id.endswith("D"):
        return contest_id[:-1], "Democrat"
    return contest_id, None


def parse_csv(csv_path: str):
    """
    Returns:
      partisan_winners:  { contest_base: { party_label: csv_winner_name } }
      judicial_winners:  { contest_id: csv_winner_name }
    """
    # { contest_id: { party: { name: votes } } }
    tallies = {}

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 6:
                continue
            office, contest_id, ballot_name, choice_id, party, total_str = row[:6]
            if ballot_name.strip() == "Total Votes":
                continue
            if not contest_id.strip():
                continue
            contest_id = contest_id.strip()
            try:
                votes = int(total_str.strip().replace(",", ""))
            except ValueError:
                continue
            party = party.strip()
            if contest_id not in tallies:
                tallies[contest_id] = {}
            if party not in tallies[contest_id]:
                tallies[contest_id][party] = {}
            tallies[contest_id][party][ballot_name.strip()] = votes

    partisan_winners = {}   # { contest_base: { party_label: winner_name } }
    judicial_winners = {}   # { contest_id: winner_name }

    for contest_id, party_data in tallies.items():
        base, party_label = get_contest_base_and_party(contest_id)

        if party_label:  # partisan
            winner_name = max(party_data.get(party_data and list(party_data.keys())[0], {}),
                              key=lambda n: party_data[list(party_data.keys())[0]][n], default=None)
            # Rebuild properly
            if party_label == "Republican":
                raw_party = "REP"
            else:
                raw_party = "DEM"
            candidates_for_party = party_data.get(raw_party, {})
            if candidates_for_party:
                winner_name = max(candidates_for_party, key=candidates_for_party.get)
                if base not in partisan_winners:
                    partisan_winners[base] = {}
                partisan_winners[base][party_label] = winner_name
        else:  # nonpartisan (no party suffix, or empty party)
            all_candidates = {}
            for p_data in party_data.values():
                all_candidates.update(p_data)
            if all_candidates:
                winner_name = max(all_candidates, key=all_candidates.get)
                judicial_winners[contest_id] = winner_name

    return partisan_winners, judicial_winners


def find_matching_candidate(winner_name: str, candidates: list):
    """Find the best matching candidate object from the list."""
    # Exact after normalization
    for c in candidates:
        if names_match(winner_name, c.get("name", "")):
            return c
    # Fallback: last name only
    winner_parts = normalize_name(winner_name).split()
    winner_last = winner_parts[-1] if winner_parts else ""
    for c in candidates:
        json_parts = normalize_name(c.get("name", "")).split()
        json_last = json_parts[-1] if json_parts else ""
        if winner_last and winner_last == json_last:
            return c
    return None


def get_race_id_for_contest(contest_id_base: str) -> str | None:
    """Map a partisan contest base to a race ID."""
    if contest_id_base in PARTISAN_MAP:
        return PARTISAN_MAP[contest_id_base]
    # State Senate: SSD{n} or SS{n}
    m = re.match(r"^SS[D]?(\d+)$", contest_id_base)
    if m:
        return f"ga-senate-{m.group(1)}-2026"
    # State House: SHD{n}
    m = re.match(r"^SHD(\d+)$", contest_id_base)
    if m:
        return f"ga-house-{m.group(1)}-2026"
    return None


def update_races(races_data: dict, partisan_winners: dict, judicial_winners: dict) -> tuple[int, list]:
    updated = 0
    skipped = []

    race_by_id = {r["id"]: r for r in races_data["races"]}

    # --- Partisan races ---
    for contest_base, party_winners in partisan_winners.items():
        race_id = get_race_id_for_contest(contest_base)
        if not race_id:
            continue
        race = race_by_id.get(race_id)
        if not race or race["activePhase"] != "primary":
            continue

        primary_ballots = race["phases"]["primary"].get("ballots", {})
        general_phase = race["phases"]["general"]

        # Build general ballots dict
        if "ballots" not in general_phase:
            general_phase["ballots"] = {}

        for party_label, winner_name in party_winners.items():
            primary_candidates = primary_ballots.get(party_label, [])
            matched = find_matching_candidate(winner_name, primary_candidates)
            if not matched:
                # If there was only one candidate on this ballot (e.g. an incumbent
                # entry with no name field), use it rather than creating a bare fallback.
                if len(primary_candidates) == 1:
                    matched = primary_candidates[0]
                    print(f"  Note: used sole primary candidate for {race_id} / {party_label} (name field absent)")
                else:
                    skipped.append(f"{race_id} / {party_label}: no match for '{winner_name}'")
                    # Still create a minimal entry
                    matched = {
                        "type": "challenger",
                        "name": winner_name,
                        "party": party_label,
                    }
            general_phase["ballots"][party_label] = [matched]

        # Remove old "candidates" key if present
        general_phase.pop("candidates", None)
        race["activePhase"] = "general"
        updated += 1

    # --- Judicial races ---
    for contest_id, winner_name in judicial_winners.items():
        race_id = JUDICIAL_MAP.get(contest_id)
        if not race_id:
            continue
        race = race_by_id.get(race_id)
        if not race or race["activePhase"] != "primary":
            continue

        primary_candidates = race["phases"]["primary"].get("candidates", [])
        matched = find_matching_candidate(winner_name, primary_candidates)
        if not matched:
            skipped.append(f"{race_id}: no match for '{winner_name}'")
            matched = {
                "type": "challenger",
                "name": winner_name,
                "party": "Non-Partisan",
            }

        race["phases"]["general"]["candidates"] = [matched]
        race["activePhase"] = "general"
        updated += 1

    return updated, skipped


def main():
    print(f"Reading CSV: {CSV_PATH}")
    partisan_winners, judicial_winners = parse_csv(CSV_PATH)
    print(f"  Partisan contests parsed: {len(partisan_winners)}")
    print(f"  Judicial contests parsed: {len(judicial_winners)}")

    with open(RACES_PATH, encoding="utf-8") as f:
        races_data = json.load(f)

    total_primary_before = sum(1 for r in races_data["races"] if r["activePhase"] == "primary")
    print(f"  Races at 'primary' before update: {total_primary_before}")

    updated, skipped = update_races(races_data, partisan_winners, judicial_winners)

    total_primary_after = sum(1 for r in races_data["races"] if r["activePhase"] == "primary")
    print(f"\nUpdated {updated} races to 'general'")
    print(f"Races at 'primary' after update: {total_primary_after}")

    if skipped:
        print(f"\nWarnings ({len(skipped)} name match issues — used fallback):")
        for s in skipped:
            print(f"  - {s}")

    with open(RACES_PATH, "w", encoding="utf-8") as f:
        json.dump(races_data, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {RACES_PATH}")


if __name__ == "__main__":
    main()
