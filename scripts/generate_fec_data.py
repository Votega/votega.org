#!/usr/bin/env python3
"""
Generate ga-fec-data.json from FEC API for GA congressional candidates.
Requires FEC_API_KEY environment variable.

Flow:
  1. GET /v1/candidates/ for GA House + Senate, cycle 2026
  2. Cross-reference with current-members.json to enrich bioguide_id
     (FEC API does not reliably return bioguide_id in candidate list responses)
  3. GET /v1/committee/{id}/totals/ for each principal committee
  4. GET /v1/schedules/schedule_a/by_employer/ for top donors by employer

Output: assets/data/ga-fec-data.json
  - candidates: keyed by FEC candidate_id
  - byBioguideId: bioguide_id -> candidate_id (for incumbent lookups)
  - byNormalizedName: normalized "first last" -> candidate_id (name-based fallback)
  - byDistrict: "H10" or "S" -> [candidate_ids] (district-scoped last-name matching)

Lookup strategy in candidate.html (findFecId):
  1. bioguide ID (incumbents with enriched data)
  2. district key + last name match (handles formal vs. nickname mismatches)
  3. normalized full name (exact FEC name match, last resort)
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
DELAY       = 0.75
TOP_N       = 10   # top employers/donors to store per candidate
FETCH_N     = 25   # fetch more from API to allow for filtered-out junk entries


def fec_get(path, params=None):
    query = {"api_key": API_KEY, "per_page": 100}
    if params:
        query.update(params)
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}"
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


def get_principal_committee_id(candidate_id):
    """The candidates list endpoint omits principal_committees.
    Use /candidate/{id}/committees/ filtered to designation='P' (principal).
    """
    data = fec_get(f"/candidate/{candidate_id}/committees/", {"designation": "P"})
    if not data or not data.get("results"):
        return None
    return data["results"][0].get("committee_id")


def get_committee_totals(committee_id):
    data = fec_get(f"/committee/{committee_id}/totals/", {"cycle": CYCLE})
    if not data or not data.get("results"):
        return None
    return data["results"][0]


def get_candidate_totals(candidate_id):
    """Fallback when principal_committees is missing from the candidate list response.
    /candidate/{id}/totals/ returns per-cycle financials without needing a committee ID.
    Field names differ from committee totals (no last_cash_on_hand_end_period).
    """
    data = fec_get(f"/candidate/{candidate_id}/totals/", {"cycle": CYCLE})
    if not data or not data.get("results"):
        return None
    return data["results"][0]


def get_top_employers(committee_id):
    # schedule_a uses two_year_transaction_period, not cycle
    data = fec_get("/schedules/schedule_a/by_employer/", {
        "committee_id":              committee_id,
        "two_year_transaction_period": CYCLE,
        "per_page":                  FETCH_N,
        "sort":                      "-total",
        "sort_hide_null":            "true",
    })
    if not data:
        return []
    results = []
    # Normalize skip set: remove spaces, hyphens, and punctuation for comparison
    _SKIP_RAW = {"NONE", "N/A", "NA", "NULL", "INFORMATION REQUESTED", "INFORMATIONREQUESTED",
                 "NOT EMPLOYED", "NOTEMPLOYED", "UNEMPLOYED", "HOMEMAKER",
                 "SELF", "SELFEMPLOYED", "SELF-EMPLOYED", "SELF EMPLOYED",
                 "RETIRED", "STUDENT"}
    SKIP_EMPLOYERS = {re.sub(r'[\s\-/]', '', s) for s in _SKIP_RAW}
    seen_employers = set()
    for r in data.get("results", []):
        emp = (r.get("employer") or "").strip()
        emp_key = re.sub(r'[\s\-/]', '', emp.upper())
        if not emp or emp_key in SKIP_EMPLOYERS or emp_key in seen_employers:
            continue
        seen_employers.add(emp_key)
        results.append({
            "employer": emp.title(),
            "total":    round(r.get("total", 0)),
            "count":    r.get("count", 0),
        })
    return results[:TOP_N]


SKIP_OCCUPATIONS = {"NONE", "N/A", "NA", "NOT EMPLOYED", "INFORMATION REQUESTED", "HOMEMAKER"}

def get_top_donors(committee_id):
    """Top individual itemized contributions sorted by amount descending.
    Uses schedule_a sorted by receipt amount. Requires a committee_id.
    """
    data = fec_get("/schedules/schedule_a/", {
        "committee_id":              committee_id,
        "two_year_transaction_period": CYCLE,
        "per_page":                  FETCH_N,
        "sort":                      "-contribution_receipt_amount",
        "sort_hide_null":            "true",
        "is_individual":             "true",
    })
    if not data:
        return []
    results = []
    seen_names = set()
    for r in data.get("results", []):
        name   = (r.get("contributor_name") or "").strip()
        amount = r.get("contribution_receipt_amount") or 0
        if not name or amount <= 0:
            continue
        name_key = re.sub(r'[^a-z]', '', name.lower())
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        employer   = (r.get("contributor_employer")   or "").strip()
        occupation = (r.get("contributor_occupation") or "").strip()
        results.append({
            "name":       name.title(),
            "amount":     round(amount),
            "employer":   employer.title()   if employer   and employer.upper()   not in SKIP_OCCUPATIONS else "",
            "occupation": occupation.title() if occupation and occupation.upper() not in SKIP_OCCUPATIONS else "",
        })
    return results[:TOP_N]


def normalize_name(name):
    """Normalize FEC name to a lookup key matching JS normalizeName() in candidate.html.
    FEC names are typically 'LAST, FIRST MIDDLE' or 'LAST, FIRST "NICK"'.
    Skips single-char initials (e.g. "OSSOFF, T. JONATHAN" -> "jonathan ossoff").
    Note: FEC formal names often differ from display names (Michael vs Mike), so
    byNormalizedName is a last-resort fallback; byBioguideId and byDistrict are preferred.
    """
    n = name.lower()
    n = re.sub(r'["\'].*?["\']', '', n)                  # strip quoted nicknames
    n = re.sub(r'\b(jr|sr|ii|iii|iv|esq)\.?\b', '', n)   # strip suffixes
    n = re.sub(r'[^a-z\s,]', '', n).strip()
    if ',' in n:
        last, first = n.split(',', 1)
        # Skip single-char initials so "T. JONATHAN" -> "jonathan", not "t"
        tokens = [t for t in first.strip().split() if len(t) > 1]
        first_name = tokens[0] if tokens else (first.strip().split() or [''])[0]
        n = f"{first_name} {last.strip()}"
    return ' '.join(n.split())


def normalize_last(name):
    """Extract normalized last name from FEC 'LAST, FIRST' format.
    Used for bioguide enrichment and the byDistrict lastName field.
    """
    last = name.split(',')[0] if ',' in name else name.split()[-1] if name.split() else ''
    return re.sub(r'[^a-z]', '', last.lower())


def load_bioguide_map():
    """Build last-name -> bioguide_id map from current-members.json for GA members.
    The FEC API does not return bioguide_id in candidate list responses, so we cross-
    reference against our own Congress member data to enrich incumbent candidates.
    Scoped to GA only to reduce false matches on common last names.
    """
    members_path = os.path.join(os.path.dirname(OUTPUT_FILE) or '.', '..', 'assets', 'data', 'current-members.json')
    for path in [members_path, 'assets/data/current-members.json']:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            result = {}
            for m in data.get('members', []):
                # current-members.json stores state as full name ("Georgia"), not abbreviation
                if m.get('state') not in ('GA', 'Georgia'):
                    continue
                last = re.sub(r'[^a-z]', '', (m.get('lastName') or '').lower())
                bioguide = m.get('bioguideId') or ''
                if last and bioguide:
                    result[last] = bioguide
            print(f"  Loaded bioguide map: {len(result)} GA members from {path}")
            return result
    print("  (current-members.json not found -- bioguide enrichment skipped)")
    return {}


def main():
    if not API_KEY:
        print("Error: FEC_API_KEY environment variable not set")
        sys.exit(1)

    print(f"\nLoading GA member bioguide map...")
    bioguide_map = load_bioguide_map()

    print(f"\nFetching GA congressional candidates from FEC (cycle {CYCLE})...")
    raw_candidates = get_ga_candidates()
    print(f"  Total: {len(raw_candidates)} candidates found")
    if not raw_candidates:
        print("Error: no candidates returned -- aborting to avoid overwriting good data")
        sys.exit(1)

    output_candidates = {}
    by_bioguide  = {}
    by_name      = {}
    # byDistrict maps "H{n}" or "S" -> [candidate_ids].
    # District is encoded in chars 4-5 of the FEC candidate_id (e.g. H8GA10071 -> district 10).
    # candidate.html uses this for district-scoped last-name matching, which handles
    # formal vs. nickname differences (e.g. FEC "MICHAEL" matching display name "Mike").
    by_district  = {}

    for i, c in enumerate(raw_candidates, 1):
        cid      = c.get("candidate_id")
        if not cid:
            continue

        name       = c.get("name", "")
        office     = c.get("office", "")        # "H" or "S"
        district   = c.get("district", "")
        bioguide   = c.get("bioguide_id") or ""
        committees = c.get("principal_committees") or []
        committee_id = committees[0].get("committee_id") if committees else None

        # List endpoint often omits principal_committees — fetch via individual detail endpoint
        if not committee_id:
            time.sleep(DELAY)
            committee_id = get_principal_committee_id(cid)

        # FEC doesn't return bioguide_id in list responses; enrich from current-members.json
        if not bioguide and bioguide_map:
            fec_last = normalize_last(name)
            bioguide = bioguide_map.get(fec_last, "")

        print(f"  [{i}/{len(raw_candidates)}] {name} ({cid}){' -> ' + bioguide if bioguide else ''}")

        entry = {
            "candidateId": cid,
            "name":        name,
            "office":      office,
            "district":    district,
            "lastName":    normalize_last(name),   # stored for district+lastName lookup in candidate.html
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
            time.sleep(DELAY)
            entry["topDonors"] = get_top_donors(committee_id)
        else:
            # principal_committees missing from list response — fall back to candidate totals
            time.sleep(DELAY)
            totals = get_candidate_totals(cid)
            if totals:
                entry["totalRaised"]     = totals.get("receipts")
                entry["totalSpent"]      = totals.get("disbursements")
                # candidate totals uses cash_on_hand_end_period; try both field variants
                entry["cashOnHand"]      = (totals.get("last_cash_on_hand_end_period")
                                            or totals.get("cash_on_hand_end_period"))
                entry["coverageEndDate"] = totals.get("coverage_end_date", "")
            entry["topEmployers"] = []
            entry["topDonors"]    = []

        output_candidates[cid] = entry

        if bioguide:
            by_bioguide[bioguide] = cid

        key = normalize_name(name)
        if key:
            by_name[key] = cid

        # Build district key from candidate_id chars 4-5 ("H8GA10071" -> "H10", "01" -> "H1")
        if office == "H" and len(cid) >= 6:
            dist_num = str(int(cid[4:6]))
            dist_key = f"H{dist_num}"
        elif office == "S":
            dist_key = "S"
        else:
            dist_key = None
        if dist_key:
            by_district.setdefault(dist_key, []).append(cid)

    output = {
        "metadata": {
            "generatedAt":    datetime.now().isoformat(),
            "cycle":          CYCLE,
            "source":         "FEC API (api.open.fec.gov)",
            "totalCandidates": len(output_candidates),
        },
        "candidates":       output_candidates,
        "byBioguideId":     by_bioguide,
        "byNormalizedName": by_name,
        "byDistrict":       by_district,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(output_candidates)} candidates | {size_kb} KB -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
