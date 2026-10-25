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
from lib.atomic_io import write_json_atomic
from lib import ga_finance_scope
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE    = "https://api-peachfile.ethics.ga.gov/api"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-campaign-finance.json"
OVERRIDES_FILE = "assets/data/ga-campaign-finance-overrides.json"
RACES_FILE  = "assets/data/races.json"
MEMBERS_FILE = "assets/data/ga-members.json"
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
    """All active filers for one office, paginated. Returns (rows, complete).

    `complete` is False when a page failed: the rows are then a prefix of the
    office, and the caller has to say so in the output rather than let a partial
    pull read as the whole record (the validator names the offices).
    """
    out, page, complete = [], 1, True
    while True:
        payload = {
            "pageNumber": page, "pageSize": PAGE_SIZE,
            "filerTypeCode": "RC", "filerName": None, "politicalPartyCode": None,
            "OfficeSought": office_id,
            "totalRaisedMax": None, "totalRaisedMin": None,
            "totalSpentMax": None, "totalSpentMin": None,
            "balanceFundsMax": None, "balanceFundsMin": None,
            # No status filter: "FACT" returned active committees only, which dropped a
            # committee's final totals the day it closed. The caller keeps active
            # filers always and a terminated one only if its seat is still in play
            # (lib/ga_finance_scope.py).
            "accountStatus": None,
            "election": None, "electionCycle": None,
            "transactionSourceTypeCode": None, "treasurerName": None,
            "jurisdictionId": None, "campaignName": None, "cityDistrictId": None,
            "districtTypeId": None, "jurisdictionIsStateOrIsCounty": None,
            "districtTypeDesc": None,
        }
        data = post("/PublicFilerDetails/GetCandidateDetails", payload)
        if not data or "data" not in data:
            print(f"    Warning: office {office_id} page {page} failed — results may be incomplete")
            complete = False
            break
        items = (data.get("data") or {}).get("items") or []
        out.extend(items)
        # totalRows is unreliable; stop on a short page instead.
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(DELAY)
    return out, complete


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


def office_entry(r, label, office_id):
    """The identity fields of a PeachFile row, shaped like a finance-file filer entry."""
    district = r.get("districtName")
    return {"firstName": r.get("candidateFirstName"), "lastName": r.get("candidateLastName"),
            "filerName": r.get("filerName"), "office": label, "officeId": office_id,
            "district": str(district) if district not in (None, "") else None}


def load_scope():
    """The seats still in play, for deciding which terminated committees to keep."""
    def read(path, key):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f).get(key) or []
        except (OSError, ValueError) as e:
            print(f"  (could not read {path}: {e}) - terminated committees will be dropped")
            return []
    return ga_finance_scope.build_scope(read(RACES_FILE, "races"), read(MEMBERS_FILE, "members"))


def main():
    cycle = target_cycle()
    print(f"Target election cycle: {cycle}")

    filers, by_seat, by_name, by_office = {}, {}, {}, {}
    skipped_other_cycle = 0
    terminated_kept, terminated_dropped = [], []
    scope = load_scope()
    rows_fetched = 0
    incomplete_offices = []   # offices whose pagination stopped on a failed page

    for office_id, (label, chamber) in OFFICES.items():
        print(f"\nFetching {label} (office {office_id})...")
        rows, complete = fetch_office(office_id)
        rows_fetched += len(rows)
        if not complete:
            incomplete_offices.append(label)
        kept = 0
        active = {ga_finance_scope.person_key(office_entry(r, label, office_id))
                  for r in rows
                  if (r.get("filerStatus") or "Active") == "Active"
                  and cycle_year(r.get("electionCycleName")) == cycle}
        for r in rows:
            if cycle_year(r.get("electionCycleName")) != cycle:
                skipped_other_cycle += 1
                continue

            fid = r.get("filerEntityId")
            if fid is None:
                continue
            fid = str(fid)
            terminated = (r.get("filerStatus") or "Active") != "Active"

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
            if terminated:
                if not ga_finance_scope.keep_terminated(entry, chamber, scope, active):
                    if fid not in terminated_dropped:
                        terminated_dropped.append(fid)
                    continue
                if fid not in terminated_kept:
                    terminated_kept.append(fid)
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

    # Nothing kept is the one case where aborting costs nothing: there is no good
    # data in this run to discard, and the committed file is left as it was. Say
    # which way it happened, because the two have different fixes.
    if not filers:
        if rows_fetched == 0:
            print("Error: the API returned no rows at all — aborting rather than "
                  "overwriting good data")
        else:
            print(f"Error: {rows_fetched} rows fetched but none belong to cycle {cycle} "
                  f"— races.json may be ahead of PeachFile; aborting rather than "
                  f"overwriting good data")
        sys.exit(1)

    # Manual resolutions for candidates the automatic join can't settle — ambiguous
    # filings, or ballot names that don't resemble the filing name. Emitted into the
    # data file so the pages need one fetch rather than two, and so a stale candidate id
    # or filer id is dropped and NAMED here instead of silently doing nothing in the browser.
    overrides = {}
    unknown = []   # overrides naming a filer the API no longer returns
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
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
        # A filer id can disappear when a committee is terminated -- a fact about the
        # Ethics Commission, not about this build. This used to sys.exit(1) here, which
        # discarded a whole run's worth of every other filer's money over one stale
        # override. The override is dropped (the candidate falls back to the automatic
        # join, which is the safe direction: a stale id must never pin a wrong
        # filing) and NAMED in metadata.droppedOverrides, which the validator reports
        # so a human re-resolves it with scripts/report_ga_finance_matches.py.
        if unknown:
            print("Warning: dropped overrides that reference filers which no longer "
                  "exist:", file=sys.stderr)
            for u in unknown:
                print(f"  - {u}", file=sys.stderr)

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "cycle":       cycle,
            "source":      "Georgia Ethics Commission PeachFile (api-peachfile.ethics.ga.gov)",
            "sourceUrl":   "https://peachfile.ethics.ga.gov/public/cf/publiccandidate",
            "coverage":    "PeachFile holds filings from 2026-01-01 onward; earlier records at https://ethics.ga.gov/records-search-all/",
            "count":       len(filers),
            # What the fetch knows about its own completeness. Read by
            # validate_ga_campaign_finance.py, which reports (never gates on) them.
            "rowsFetched":       rows_fetched,
            "incompleteOffices": incomplete_offices,
            "droppedOverrides":  unknown,
            # Terminated committees whose seat is still held or contested are kept (their
            # entry carries filerStatus); the rest are counted, not published.
            "terminatedKept":    sorted(terminated_kept),
            "terminatedDropped": len(terminated_dropped),
        },
        "filers":           filers,
        "candidateOverrides": overrides,
        "bySeat":           by_seat,
        "byNormalizedName": by_name,
        "byOffice":         by_office,
    }

    write_json_atomic(OUTPUT_FILE, output, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(filers)} filers for cycle {cycle} "
          f"({skipped_other_cycle} skipped from other cycles, "
          f"{len(terminated_kept)} terminated kept, {len(terminated_dropped)} dropped) | {size_kb} KB -> {OUTPUT_FILE}")
    print(f"  seats covered: {len(by_seat)} | statewide offices: {len(by_office)} "
          f"| manual overrides: {len(overrides)}")


if __name__ == "__main__":
    main()
