"""
Watches the Downloads folder for new SOS candidate CSV files.
Each time a new CSV lands, it's parsed and merged into
assets/data/ga-legislative-candidates.json automatically.

Usage:
  python scripts/watch_downloads.py

Then in your browser:
  1. Go to https://mvp.sos.ga.gov/s/qualifying-candidate-information
  2. Set Election Year = 2026, Election = May 19 Primary
  3. Set Party = Democrat, Contest Type = State Race, Contest = (leave ALL or pick a type)
  4. Click VIEW QUALIFIED CANDIDATES, then the Export/Download button
  5. Repeat for Republican
  6. Repeat for State Senate if needed
  Ctrl+C when done.
"""
import csv, json, os, re, time
from pathlib import Path

DOWNLOADS   = Path(r"C:\Users\justi\Downloads")
OUT_PATH    = Path("assets/data/ga-legislative-candidates.json")
CSV_PATTERN = re.compile(r".*candidate.*\.csv$|.*qualif.*\.csv$|.*district.*\.csv$|.*state.*race.*\.csv$|.*house.*\.csv$|.*senate.*\.csv$", re.IGNORECASE)

REQUIRED_COLS = {"CONTEST NAME", "CANDIDATE NAME", "POLITICAL PARTY", "CANDIDATE STATUS"}

def is_sos_csv(path: Path) -> bool:
    """Check if this CSV has the SOS column structure."""
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames or [])
            return bool(cols & REQUIRED_COLS)
    except Exception:
        return False

def parse_csv(path: Path) -> dict:
    """Parse SOS CSV -> {contest_name: [candidate_dict, ...]}"""
    data = {}
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            contest = row.get('CONTEST NAME', '').strip()
            if not contest:
                continue
            if contest not in data:
                data[contest] = []
            raw_name = row.get('CANDIDATE NAME', '').strip()
            name_parts = raw_name.split()
            website = row.get('WEBSITE', '').strip()
            if website and not website.lower().startswith('http'):
                website = 'https://' + website.lower()
            data[contest].append({
                "_source": "csv",
                "Official_FullName__c": raw_name,
                "Name__c": name_parts[0] if name_parts else '',
                "Last_Name__c": name_parts[-1] if name_parts else '',
                "Name_on_Ballot__c": raw_name,
                "Candidate_Party__c": row.get('POLITICAL PARTY', '').strip(),
                "vr_Political_Party__c": row.get('POLITICAL PARTY', '').strip(),
                "Incumbent__c": row.get('INCUMBENT', '').strip().upper() == 'YES',
                "Declaration__c": row.get('CANDIDATE STATUS', '').strip(),
                "Occupation__c": row.get('OCCUPATION', '').strip(),
                "Email__c": row.get('EMAIL ADDRESS', '').strip(),
                "Campaign_Website__c": website,
                "County__c": row.get('COUNTY', '').strip(),
                "Date_Qualified__c": row.get('QUALIFIED DATE', '').strip(),
                "Elected_Office__r": {"Name": contest},
            })
    return data

def load_existing() -> dict:
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {
        "election": "a0pcs00000J6e6HAAR",
        "electionDate": "2026-05-19",
        "updatedAt": "",
        "results": {"Democrat": {}, "Republican": {}, "Other": {}},
        "errors": [],
        "csvFilesProcessed": []
    }

def save(data: dict):
    data["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(OUT_PATH, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def merge_csv_into(store: dict, csv_data: dict, filename: str):
    """Merge parsed CSV data into the store, return count of new/updated candidates."""
    results = store.setdefault("results", {"Democrat": {}, "Republican": {}, "Other": {}})
    new_count = 0
    updated_contests = set()

    for contest, cands in csv_data.items():
        # Determine party bucket from contest name suffix
        m = re.search(r'\(([DR])\)', contest)
        if m:
            party_key = "Democrat" if m.group(1) == "D" else "Republican"
        else:
            # Fallback: use party from first candidate
            first_party = cands[0].get("Candidate_Party__c", "") if cands else ""
            party_key = first_party if first_party in ("Democrat", "Republican") else "Other"

        bucket = results.setdefault(party_key, {})
        existing = bucket.get(contest, [])
        existing_names = {c["Official_FullName__c"] for c in existing}

        added = 0
        for c in cands:
            if c["Official_FullName__c"] not in existing_names:
                existing.append(c)
                added += 1

        bucket[contest] = existing
        if added:
            new_count += added
            updated_contests.add(contest)

    processed = store.setdefault("csvFilesProcessed", [])
    processed.append({"file": filename, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "contests": sorted(updated_contests)})
    return new_count, updated_contests

def summary(store: dict):
    r = store.get("results", {})
    total_contests = sum(len(v) for v in r.values())
    total_cands    = sum(len(c) for v in r.values() for c in v.values())
    d = len(r.get("Democrat", {}))
    rep = len(r.get("Republican", {}))
    return f"{total_contests} contests ({d}D / {rep}R), {total_cands} candidates"


def main():
    print("=== GA SOS CSV Watcher ===")
    print(f"Watching: {DOWNLOADS}")
    print(f"Output:   {OUT_PATH}")
    print()
    print("Instructions:")
    print("  Go to https://mvp.sos.ga.gov/s/qualifying-candidate-information")
    print("  Election Year: 2026  |  Election: May 19 Primary")
    print("  Try leaving Contest blank (All) to get all races in one download.")
    print("  Download for: Democrat/State Race, Republican/State Race,")
    print("                Democrat/State Senate Race, Republican/State Senate Race")
    print("  Ctrl+C when done.")
    print()

    store = load_existing()
    print(f"Existing data: {summary(store)}")
    print()

    # Track files already present when we start
    seen = {p: p.stat().st_mtime for p in DOWNLOADS.glob("*.csv")}
    print(f"Ignoring {len(seen)} existing CSV(s) in Downloads.")
    print("Waiting for new downloads...\n")

    try:
        while True:
            time.sleep(2)
            for path in DOWNLOADS.glob("*.csv"):
                mtime = path.stat().st_mtime
                if path not in seen:
                    seen[path] = mtime
                    # Give the file a moment to finish writing
                    time.sleep(1)
                    if not is_sos_csv(path):
                        print(f"  Skipping {path.name} (not a SOS candidate CSV)")
                        continue
                    print(f"  Detected: {path.name}")
                    try:
                        csv_data = parse_csv(path)
                        n_contests = len(csv_data)
                        n_cands    = sum(len(v) for v in csv_data.values())
                        new_c, updated = merge_csv_into(store, csv_data, path.name)
                        save(store)
                        print(f"  Merged: {n_contests} contests, {n_cands} rows, {new_c} new candidates added")
                        print(f"  Running total: {summary(store)}")
                        if updated:
                            sample = list(updated)[:3]
                            print(f"  Sample contests: {', '.join(sample)}")
                        print()
                    except Exception as e:
                        print(f"  ERROR processing {path.name}: {e}")
    except KeyboardInterrupt:
        print("\nDone. Final state:")
        print(f"  {summary(store)}")
        print(f"  Saved to {OUT_PATH}")

if __name__ == "__main__":
    main()
