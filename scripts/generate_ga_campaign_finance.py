#!/usr/bin/env python3
"""
Generate ga-campaign-finance.json from the Georgia Ethics Commission's PeachFile API.

This is the state-level counterpart to generate_fec_data.py. No API key is required,
but the API is CORS origin-locked, so the site cannot call it from the browser — the
data has to be fetched at build time and served as static JSON.

Flow:
  1. POST /PublicFilerDetails/GetCandidateDetails once per office, paginated
  2. Keep only filers in the target election cycle
  3. Build lookups keyed to ga-members.json (chamber + district, and normalized name)

Output: assets/data/ga-campaign-finance.json
  - filers:           keyed by filerEntityId
  - bySeat:           "House-13" / "Senate-39" -> [filerEntityId]  (primary join)
  - byNormalizedName: "john guest" -> filerEntityId                (fallback)
  - byOffice:         "Governor" -> [filerEntityId]                (statewide races)

Notes on the API, all learned the hard way:
  - pageSize above ~100 trips a WAF that returns {"message":"Potentially harmful
    payload detected!"} rather than an HTTP error.
  - The `totalRows` field is unreliable (observed 3 on a 5-item response), so
    pagination stops on a short page instead of trusting a count.
  - A single office query mixes election cycles: the current general, the next one,
    individual special elections, and a historical "supplemental" bucket. Filtering
    on the cycle year is required or a candidate's next-cycle committee totals will
    be shown against this cycle's race.
  - PeachFile only holds records from 2026-01-01 onward. Earlier filings live at
    https://ethics.ga.gov/records-search-all/
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

API_BASE    = "https://api-peachfile.ethics.ga.gov/api"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-campaign-finance.json"
OVERRIDES_FILE = "assets/data/ga-campaign-finance-overrides.json"
RACES_FILE  = "assets/data/races.json"
PAGE_SIZE   = 100          # anything much larger is rejected by the WAF
DELAY       = 1.0
FALLBACK_CYCLE = 2026      # only used if races.json can't be read

# officeId -> (label, chamber-for-join or None for statewide)
OFFICES = {
    "10": ("State Representative", "House of Representatives"),
    "11": ("State Senator",        "Senate"),
    "17": ("Governor",             None),
    "19": ("Lieutenant Governor",  None),
    "20": ("Secretary of State",   None),
    "12": ("Attorney General",     None),
    "13": ("Commissioner of Agriculture", None),
    "14": ("Commissioner of Insurance",   None),
    "15": ("Commissioner of Labor",       None),
    "21": ("State School Superintendent", None),
    "9":  ("Public Service Commissioner", None),
}


def post(path, payload, retries=3):
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json",
                         "User-Agent": "votega.org/1.0 (+https://www.votega.org)"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Retry only on rate limiting and server errors; 4xx is our fault.
            if e.code == 429 or e.code >= 500:
                wait = 15 * attempt
                print(f"    HTTP {e.code} — retrying in {wait}s ({attempt}/{retries})")
                time.sleep(wait)
            else:
                print(f"    Error {path}: HTTP {e.code}")
                return None
        except Exception as e:
            print(f"    Error {path}: {e}")
            time.sleep(5 * attempt)
    print(f"    Giving up on {path} after {retries} retries")
    return None


def target_cycle():
    """Newest cycle present in races.json, so a new cycle is a data change not a code one."""
    try:
        with open(RACES_FILE, encoding="utf-8") as f:
            cycles = [r.get("cycle") for r in json.load(f).get("races", []) if r.get("cycle")]
        if cycles:
            return max(cycles)
    except Exception as e:
        print(f"  (could not read {RACES_FILE}: {e})")
    return FALLBACK_CYCLE


def cycle_year(name):
    """Leading year of an electionCycleName, e.g. '2026 Georgia State Election' -> 2026."""
    m = re.match(r"\s*(\d{4})", name or "")
    return int(m.group(1)) if m else None


def fetch_office(office_id):
    """All active filers for one office, paginated."""
    out, page = [], 1
    while True:
        payload = {
            "pageNumber": page, "pageSize": PAGE_SIZE,
            "filerTypeCode": "RC", "filerName": None, "politicalPartyCode": None,
            "OfficeSought": office_id,
            "totalRaisedMax": None, "totalRaisedMin": None,
            "totalSpentMax": None, "totalSpentMin": None,
            "balanceFundsMax": None, "balanceFundsMin": None,
            "accountStatus": "FACT",       # active committees only
            "election": None, "electionCycle": None,
            "transactionSourceTypeCode": None, "treasurerName": None,
            "jurisdictionId": None, "campaignName": None, "cityDistrictId": None,
            "districtTypeId": None, "jurisdictionIsStateOrIsCounty": None,
            "districtTypeDesc": None,
        }
        data = post("/PublicFilerDetails/GetCandidateDetails", payload)
        if not data or "data" not in data:
            print(f"    Warning: office {office_id} page {page} failed — results may be incomplete")
            break
        items = (data.get("data") or {}).get("items") or []
        out.extend(items)
        # totalRows is unreliable; stop on a short page instead.
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(DELAY)
    return out


def norm_name(first, last, full):
    """'john guest' style key, matching normalizeName() used on the pages."""
    if first and last:
        base = f"{first} {last}"
    elif full and "," in full:
        l, f = full.split(",", 1)
        base = f"{f.strip()} {l.strip()}"
    else:
        base = full or ""
    base = base.lower()
    base = re.sub(r'["\'].*?["\']', "", base)
    base = re.sub(r"\b(jr|sr|ii|iii|iv|dr|mr|mrs|ms|esq)\.?\b", "", base)
    base = re.sub(r"[^a-z\s]", "", base)
    return " ".join(base.split())


def main():
    cycle = target_cycle()
    print(f"Target election cycle: {cycle}")

    filers, by_seat, by_name, by_office = {}, {}, {}, {}
    skipped_other_cycle = 0

    for office_id, (label, chamber) in OFFICES.items():
        print(f"\nFetching {label} (office {office_id})...")
        rows = fetch_office(office_id)
        kept = 0
        for r in rows:
            if cycle_year(r.get("electionCycleName")) != cycle:
                skipped_other_cycle += 1
                continue

            fid = r.get("filerEntityId")
            if fid is None:
                continue
            fid = str(fid)

            district = r.get("districtName")
            entry = {
                "filerEntityId":  fid,
                "filerName":      r.get("filerName"),
                "firstName":      r.get("candidateFirstName"),
                "lastName":       r.get("candidateLastName"),
                "office":         label,
                "officeId":       office_id,
                "district":       str(district) if district not in (None, "") else None,
                "party":          r.get("politicalPartyCode"),
                "totalRaised":    r.get("totalContributions"),
                "totalSpent":     r.get("totalExpenditures"),
                "cashOnHand":     r.get("cashOnHand"),
                "electionCycle":  r.get("electionCycleName"),
            }
            # Only carry fields that say something: the search URL is a constant (see
            # metadata.sourceUrl) and most committees are Active. Repeating either on
            # every filer added ~170 KB to a file the member pages download.
            if r.get("committeeName"):
                entry["committeeName"] = r["committeeName"]
            if r.get("filerStatus") and r["filerStatus"] != "Active":
                entry["filerStatus"] = r["filerStatus"]
            filers[fid] = entry
            kept += 1

            # Dedupe on insert: the API returns the same filerEntityId on several rows
            # (one per associated election), so appending blindly put one filer in a
            # bucket up to eight times and made a single candidate look like a seat full
            # of same-named filers to any consumer checking for ambiguity.
            if chamber and entry["district"]:
                bucket = by_seat.setdefault(f"{chamber}-{entry['district']}", [])
            else:
                bucket = by_office.setdefault(label, [])
            if fid not in bucket:
                bucket.append(fid)

            key = norm_name(entry["firstName"], entry["lastName"], entry["filerName"])
            if key:
                by_name.setdefault(key, fid)

        print(f"  {len(rows)} fetched, {kept} kept for cycle {cycle}")
        time.sleep(DELAY)

    if not filers:
        print("Error: no filers collected — aborting rather than overwriting good data")
        sys.exit(1)

    # Manual resolutions for candidates the automatic join can't settle — ambiguous
    # filings, or ballot names that don't resemble the filing name. Emitted into the
    # data file so the pages need one fetch rather than two, and so a bad candidate id
    # or filer id fails the build here instead of silently doing nothing in the browser.
    overrides = {}
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        unknown = []
        for key, val in raw.items():
            if key.startswith("_"):
                continue
            fid = val.get("filerEntityId")
            if fid and str(fid) not in filers:
                unknown.append(f"{key} -> filerEntityId {fid}")
                continue
            entry = {}
            if fid:
                entry["filerEntityId"] = str(fid)
            if val.get("noFiling"):
                entry["noFiling"] = True
            if entry:
                overrides[key] = entry
        print(f"\nLoaded {len(overrides)} manual override(s) from {OVERRIDES_FILE}")
        if unknown:
            print("Error: overrides reference filers that no longer exist:", file=sys.stderr)
            for u in unknown:
                print(f"  - {u}", file=sys.stderr)
            print("  Re-run scripts/report_ga_finance_matches.py and re-resolve those "
                  "candidates; a filer id can disappear when a committee is terminated.",
                  file=sys.stderr)
            sys.exit(1)

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "cycle":       cycle,
            "source":      "Georgia Ethics Commission PeachFile (api-peachfile.ethics.ga.gov)",
            "sourceUrl":   "https://peachfile.ethics.ga.gov/public/cf/publiccandidate",
            "coverage":    "PeachFile holds filings from 2026-01-01 onward; earlier records at https://ethics.ga.gov/records-search-all/",
            "count":       len(filers),
        },
        "filers":           filers,
        "candidateOverrides": overrides,
        "bySeat":           by_seat,
        "byNormalizedName": by_name,
        "byOffice":         by_office,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(filers)} filers for cycle {cycle} "
          f"({skipped_other_cycle} skipped from other cycles) | {size_kb} KB -> {OUTPUT_FILE}")
    print(f"  seats covered: {len(by_seat)} | statewide offices: {len(by_office)} "
          f"| manual overrides: {len(overrides)}")


if __name__ == "__main__":
    main()
