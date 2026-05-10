#!/usr/bin/env python3
"""
Generate ga-fec-data.json from FEC API for GA congressional candidates.
Requires FEC_API_KEY environment variable.

Flow:
  1. GET /v1/candidates/ for GA House + Senate, cycle 2026
  2. GET /v1/committee/{id}/totals/ for each principal committee
  3. GET /v1/schedules/schedule_a/by_employer/ for top donors by employer

Output: assets/data/ga-fec-data.json
  Keyed by FEC candidate_id, with lookup indexes by bioguideId and normalized name.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime

API_KEY     = os.environ.get('FEC_API_KEY')
BASE_URL    = "https://api.open.fec.gov/v1"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-fec-data.json"
CYCLE       = 2026
DELAY       = 0.5
TOP_N       = 10   # top employers to store per candidate


def fec_get(path, params=None):
    query = {"api_key": API_KEY, "per_page": 100}
    if params:
        query.update(params)
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}"
    safe = url.replace(API_KEY, "***") if API_KEY else url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "votega.org/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"    Error {path}: {e}")
        return None


def get_ga_candidates():
    candidates = []
    for office in ("H", "S"):
        data = fec_get("/candidates/", {
            "state": "GA", "office": office, "cycle": CYCLE,
            "sort": "name", "per_page": 100
        })
        if data:
            results = data.get("results", [])
            candidates.extend(results)
            print(f"  GA {office}: {len(results)} candidates")
        time.sleep(DELAY)
    return candidates


def get_committee_totals(committee_id):
    data = fec_get(f"/committee/{committee_id}/totals/", {"cycle": CYCLE})
    if not data or not data.get("results"):
        return None
    return data["results"][0]


def get_top_employers(committee_id):
    # schedule_a uses two_year_transaction_period, not cycle
    data = fec_get("/schedules/schedule_a/by_employer/", {
        "committee_id":              committee_id,
        "two_year_transaction_period": CYCLE,
        "per_page":                  TOP_N,
        "sort":                      "-total",
        "sort_hide_null":            "true",
    })
    if not data:
        return []
    results = []
    for r in data.get("results", []):
        emp = (r.get("employer") or "").strip()
        if not emp or emp.upper() in ("NONE", "N/A", "NA", "INFORMATION REQUESTED"):
            continue
        results.append({
            "employer": emp.title(),
            "total":    round(r.get("total", 0)),
            "count":    r.get("count", 0),
        })
    return results[:TOP_N]


def normalize_name(name):
    """Normalize FEC name to a lookup key matching JS normalization.
    FEC names are typically 'LAST, FIRST MIDDLE' or 'LAST, FIRST "NICK"'.
    Output: 'first last' (lowercase, no punctuation, no suffixes/nicknames).
    """
    n = name.lower()
    n = re.sub(r'["\'].*?["\']', '', n)                  # strip quoted nicknames
    n = re.sub(r'\b(jr|sr|ii|iii|iv|esq)\.?\b', '', n)   # strip suffixes
    n = re.sub(r'[^a-z\s,]', '', n).strip()
    if ',' in n:
        last, first = n.split(',', 1)
        n = f"{first.strip().split()[0]} {last.strip()}"  # first-token of first + last
    return ' '.join(n.split())


def main():
    if not API_KEY:
        print("Error: FEC_API_KEY environment variable not set")
        sys.exit(1)

    print(f"Fetching GA congressional candidates from FEC (cycle {CYCLE})...")
    raw_candidates = get_ga_candidates()
    print(f"  Total: {len(raw_candidates)} candidates found")
    if not raw_candidates:
        print("Error: no candidates returned — aborting to avoid overwriting good data")
        sys.exit(1)

    output_candidates = {}
    by_bioguide = {}
    by_name     = {}

    for i, c in enumerate(raw_candidates, 1):
        cid      = c.get("candidate_id")
        if not cid:
            continue

        name       = c.get("name", "")
        office     = c.get("office", "")
        district   = c.get("district", "")
        bioguide   = c.get("bioguide_id") or ""
        committees = c.get("principal_committees") or []
        committee_id = committees[0].get("committee_id") if committees else None

        print(f"  [{i}/{len(raw_candidates)}] {name} ({cid})")

        entry = {
            "candidateId": cid,
            "name":        name,
            "office":      office,
            "district":    district,
            "fecUrl":      f"https://www.fec.gov/data/candidate/{cid}/",
        }
        if bioguide:
            entry["bioguideId"] = bioguide
        if committee_id:
            entry["committeeId"] = committee_id

        if committee_id:
            time.sleep(DELAY)
            totals = get_committee_totals(committee_id)
            if totals:
                entry["totalRaised"]     = totals.get("receipts")
                entry["totalSpent"]      = totals.get("disbursements")
                entry["cashOnHand"]      = (totals.get("last_cash_on_hand_end_period")
                                            or totals.get("cash_on_hand_end_period"))
                entry["coverageEndDate"] = totals.get("coverage_end_date", "")

            time.sleep(DELAY)
            entry["topEmployers"] = get_top_employers(committee_id)
        else:
            entry["topEmployers"] = []

        output_candidates[cid] = entry

        if bioguide:
            by_bioguide[bioguide] = cid
        key = normalize_name(name)
        if key:
            by_name[key] = cid

    output = {
        "metadata": {
            "generatedAt":    datetime.now().isoformat(),
            "cycle":          CYCLE,
            "source":         "FEC API (api.open.fec.gov)",
            "totalCandidates": len(output_candidates),
        },
        "candidates":      output_candidates,
        "byBioguideId":    by_bioguide,
        "byNormalizedName": by_name,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(output_candidates)} candidates · {size_kb} KB → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
