"""
Convert ga-legislative-candidates.json into races.json entries
for all GA State House and Senate districts.
"""
import json, re, string
from pathlib import Path

SRC  = Path("assets/data/ga-legislative-candidates.json")
DEST = Path("assets/data/races.json")

def title_case(name: str) -> str:
    """Convert ALL CAPS name to Title Case, handling common edge cases."""
    if not name:
        return name
    # Words that should stay lower (unless first word)
    lower_words = {"a","an","the","and","or","of","in","on","for","to","at","by","from","with"}
    words = name.lower().split()
    result = []
    for i, w in enumerate(words):
        # Always capitalize first word, single letters (initials), or non-minor words
        if i == 0 or len(w) == 1 or w not in lower_words:
            # Handle hyphenated names
            if '-' in w:
                w = '-'.join(p.capitalize() for p in w.split('-'))
            else:
                w = w.capitalize()
        result.append(w)
    return ' '.join(result)

def normalize_website(url: str) -> str:
    if not url:
        return ''
    url = url.strip()
    if not url:
        return ''
    if not url.lower().startswith('http'):
        url = 'https://' + url.lower()
    return url

def make_candidate_id(chamber_slug: str, district: int, party_slug: str, idx: int) -> str:
    return f"ga-{chamber_slug}-{district}-2026-{party_slug}-{idx+1}"

def make_race_id(chamber_slug: str, district: int) -> str:
    return f"ga-{chamber_slug}-{district}-2026"

def parse_district(contest_name: str):
    """Extract district number from 'State House, District 12 (D)' -> 12"""
    m = re.search(r'District\s+(\d+)', contest_name, re.IGNORECASE)
    return int(m.group(1)) if m else None

def candidate_from_row(row: dict, idx: int, chamber_slug: str, district: int, party_slug: str) -> dict:
    name = title_case(row.get("Official_FullName__c") or row.get("Name_on_Ballot__c") or "")
    is_incumbent = bool(row.get("Incumbent__c"))
    is_disqualified = (row.get("Declaration__c") or "").lower() == "disqualified"

    c = {
        "id": make_candidate_id(chamber_slug, district, party_slug, idx),
        "type": "challenger",
        "name": name,
        "party": row.get("Candidate_Party__c") or row.get("vr_Political_Party__c") or "",
        "occupation": title_case(row.get("Occupation__c") or ""),
        "county": title_case(row.get("County__c") or ""),
    }
    if is_incumbent:
        c["isIncumbent"] = True
    if is_disqualified:
        c["withdrawn"] = True

    website = normalize_website(row.get("Campaign_Website__c") or "")
    if website:
        c["website"] = website

    email = (row.get("Email__c") or "").strip().lower()
    if email:
        c["email"] = email

    return c

def build_races(src_data: dict) -> list:
    """Build list of race dicts from the collected candidate data."""
    races = []

    # Collect all districts from both parties
    # Key: (chamber_slug, district_num)  ->  { "Democrat": [rows], "Republican": [rows] }
    districts = {}

    for party_label in ("Democrat", "Republican"):
        party_slug = "d" if party_label == "Democrat" else "r"
        contests = src_data["results"].get(party_label, {})
        for contest_name, rows in contests.items():
            if "State House" not in contest_name and "State Senate" not in contest_name:
                continue
            if "Special Election" in contest_name:
                continue  # special elections are separate races; skip to avoid duplicate candidates
            district = parse_district(contest_name)
            if district is None:
                continue
            chamber_slug = "house" if "State House" in contest_name else "senate"
            key = (chamber_slug, district)
            if key not in districts:
                districts[key] = {"Democrat": [], "Republican": []}
            districts[key][party_label].extend(rows)

    # Build one race per district
    for (chamber_slug, district), parties in sorted(districts.items(), key=lambda x: (x[0][0], x[0][1])):
        chamber_name = "Georgia House of Representatives" if chamber_slug == "house" else "Georgia State Senate"

        ballots = {}
        for party_label in ("Democrat", "Republican"):
            party_slug = "d" if party_label == "Democrat" else "r"
            rows = parties[party_label]
            if not rows:
                continue
            cands = [
                candidate_from_row(row, i, chamber_slug, district, party_slug)
                for i, row in enumerate(rows)
            ]
            ballots[party_label] = cands

        if not ballots:
            continue

        race = {
            "id":          make_race_id(chamber_slug, district),
            "level":       "state",
            "chamber":     chamber_name,
            "district":    district,
            "cycle":       2026,
            "activePhase": "primary",
            "phases": {
                "primary": {
                    "electionDate": "2026-05-19",
                    "ballots": ballots
                },
                "general": {
                    "electionDate": "2026-11-03",
                    "candidates": []
                }
            }
        }
        races.append(race)

    return races

def main():
    with open(SRC, encoding="utf-8") as f:
        src = json.load(f)

    new_races = build_races(src)
    print(f"Built {len(new_races)} legislative race entries")

    # Load existing races.json and remove any old ga-house/ga-senate entries
    with open(DEST, encoding="utf-8") as f:
        dest = json.load(f)

    existing = [r for r in dest.get("races", [])
                if not r["id"].startswith("ga-house-") and not r["id"].startswith("ga-senate-")]
    dest["races"] = existing + new_races
    dest["updatedAt"] = src.get("updatedAt", "")

    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(dest, f, indent=2, ensure_ascii=False)

    # Stats
    house  = [r for r in new_races if r["chamber"] == "Georgia House of Representatives"]
    senate = [r for r in new_races if r["chamber"] == "Georgia State Senate"]
    total_cands = sum(
        len(cands)
        for r in new_races
        for cands in r["phases"]["primary"]["ballots"].values()
    )
    print(f"  House races:  {len(house)}")
    print(f"  Senate races: {len(senate)}")
    print(f"  Total candidates across all ballots: {total_cands}")
    print(f"  Total races in races.json: {len(dest['races'])}")

if __name__ == "__main__":
    main()
