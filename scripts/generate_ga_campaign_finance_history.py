#!/usr/bin/env python3
"""
Generate ga-campaign-finance-history.json from the Georgia Ethics Commission's
LEGACY records search API (pre-2026 filings).

This is the historical counterpart to generate_ga_campaign_finance.py. The two
systems are separate applications over separate databases:

  legacy    api-recordsearch.ethics.ga.gov  filings through 2025-12-31
  PeachFile api-peachfile.ethics.ga.gov     filings from 2026-01-01 onward

What this file is good for, and what it is NOT
----------------------------------------------
It is a historical record: prior-cycle committee filings (2022 has 704 records,
2024 has 417) that exist nowhere else in machine-readable form.

It CANNOT be subtracted from PeachFile to derive "raised this cycle". That was
the original motivation and it does not survive measurement. On a 17-candidate
Governor-only sample PeachFile was >= legacy in every case, which looked like
clean carry-forward; across all 239 filers matched in both systems, 55 have
PeachFile BELOW legacy (Karen Mathiak: $341,493 legacy vs $49,375 PeachFile).
A cash-on-hand continuity model — PeachFile cash == legacy cash + raised - spent
— holds for only 21% of matches, worse than PeachFile's own internal consistency
of 36%. Any "raised this cycle" figure derived by subtraction would be negative
for roughly a quarter of legislative filers.

The underlying problem is that `totalContributions` semantics are undocumented
and appear to differ between the two systems, and possibly between filers within
one system. Karla Drenner's legacy records read $123,470 for 2022 and $125,770
for 2026 — a $2,300 difference across a full cycle — which suggests the legacy
figure is a running lifetime total rather than per-cycle. If so, even a
standalone "raised in 2022" reading of this data is unsafe.

Treat the totals as reported figures of uncertain period. This is an open
question with the Ethics Commission, not a bug in this script.

API notes (same engine as PeachFile, so most quirks carry over)
--------------------------------------------------------------
  - Same POST contract, no authentication, same WAF: pageSize above ~100 returns
    {"message":"Potentially harmful payload detected!"} rather than an HTTP error.
  - UNLIKE PeachFile, `totalItems` here is reliable, so it is used to detect a
    short read. Pagination still stops on a short page as a backstop.
  - Office IDs are RENUMBERED relative to PeachFile and must not be shared.
    Governor is 19 here but 17 in PeachFile; 12 is City Councilperson here but
    Attorney General there. Pointing PeachFile's OFFICES map at this host would
    silently fetch the wrong offices.
  - `accountStatus: "FACT"` (PeachFile's active-committee filter) matches nothing
    here; the legacy system uses filerStatusCode instead.
  - filerEntityId is NOT a shared key. The ranges overlap numerically (legacy
    1,271-852,246 vs PeachFile 100,008-105,462) while referring to different
    entities, so joining the two files on filer id yields silent false matches.
    Join on office + district + normalized name instead. Every record here is
    tagged `"source": "legacy"` so the two can never be confused downstream.
  - Special elections are separate cycles with irregular names ("June 2021
    Special Election Cycle", "General Election 2016-11-08 for Candidates"), so
    the cycle year is extracted by search, not by a leading-year match.

Output: assets/data/ga-campaign-finance-history.json

Usage:
  python scripts/generate_ga_campaign_finance_history.py [outfile]
      --judicial     also fetch statewide judicial offices
      --local        also fetch county/municipal offices (large; not used by the site)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

API_BASE    = "https://api-recordsearch.ethics.ga.gov/api"
OUTPUT_FILE = "assets/data/ga-campaign-finance-history.json"
PAGE_SIZE   = 100          # anything larger is rejected by the WAF
DELAY       = 0.5

# Legacy officeId -> (label, chamber-for-seat-join or None for statewide).
# Labels are normalised to match generate_ga_campaign_finance.py so the two
# files can be joined on `office` without a translation table.
OFFICES = {
    "14": ("State Representative", "House of Representatives"),
    "37": ("State Senator",        "Senate"),
    "19": ("Governor",             None),
    "46": ("Lieutenant Governor",  None),
    "21": ("Secretary of State",   None),
    "23": ("Attorney General",     None),
    "6":  ("Commissioner of Agriculture", None),
    "48": ("Commissioner of Insurance",   None),
    "9":  ("Commissioner of Labor",       None),
    "35": ("State School Superintendent", None),
    "2":  ("Public Service Commissioner", None),
}

JUDICIAL_OFFICES = {
    "3":  ("Justice of the Supreme Court", None),
    "20": ("Court of Appeals Judge",       None),
}

# Fetched only with --local. Useful for a public data release, but the site has
# no page that consumes county or municipal filings.
LOCAL_OFFICES = {
    "7":  ("Mayor",                  None),
    "12": ("City Councilperson",     None),
    "24": ("County Commissioner",    None),
    "29": ("County Commission Chair", None),
    "33": ("Board of Education",     None),
    "16": ("Sheriff",                None),
    "32": ("District Attorney",      None),
    "49": ("Superior Court Judge",   None),
    "40": ("State Court Judge",      None),
    "41": ("Tax Commissioner",       None),
    "42": ("Clerk of Superior Court", None),
    "10": ("Probate Court Judge",    None),
    "15": ("Chief Magistrate Judge", None),
    "39": ("Solicitor General",      None),
    "43": ("Coroner",                None),
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


def cycle_year(name):
    """Year of an electionCycleName.

    Cycle names are not uniform. Most lead with the year ("2022 State/Statewide
    Election Cycle..."), but special elections do not ("June 2021 Special
    Election Cycle", "General Election 2016-11-08 for Candidates"), so fall back
    to the first plausible year anywhere in the string.
    """
    name = name or ""
    m = re.match(r"\s*((?:19|20)\d{2})", name)
    if m:
        return int(m.group(1))
    m = re.search(r"\b((?:19|20)\d{2})\b", name)
    return int(m.group(1)) if m else None


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
    # Apostrophes are intra-word, not separators: O'Steen and Osteen must
    # normalise to the same key. Strip rather than replace with a space.
    base = base.replace("'", "").replace("’", "")
    base = re.sub(r"\b(jr|sr|ii|iii|iv|dr|mr|mrs|ms|esq)\.?\b", "", base)
    base = re.sub(r"[^a-z\s]", "", base)
    return " ".join(base.split())


def fetch_office(office_id, label):
    """All filers for one office, paginated. Returns (rows, expected_total)."""
    out, page, expected = [], 1, None
    while True:
        payload = {
            "pageNumber": page, "pageSize": PAGE_SIZE,
            "OfficeSought": office_id,
            "filerName": None, "politicalPartyCode": None,
            "totalRaisedMax": None, "totalRaisedMin": None,
            "totalSpentMax": None, "totalSpentMin": None,
            "balanceFundsMax": None, "balanceFundsMin": None,
            "election": None, "electionCycle": None,
            "treasurerName": None, "jurisdictionId": None,
            "campaignName": None, "cityDistrictId": None,
            "districtTypeId": None, "districtTypeDesc": None,
        }
        data = post("/PublicFilerDetails/GetCandidateDetails", payload)
        if not data or "data" not in data:
            print(f"    Warning: {label} page {page} failed — results may be incomplete")
            break
        block = data.get("data") or {}
        items = block.get("items") or []
        if expected is None:
            expected = block.get("totalItems")
        out.extend(items)
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(DELAY)
    return out, expected


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    outfile = args[0] if args else OUTPUT_FILE

    offices = dict(OFFICES)
    if "--judicial" in sys.argv:
        offices.update(JUDICIAL_OFFICES)
    if "--local" in sys.argv:
        offices.update(LOCAL_OFFICES)

    filers, by_seat, by_office, by_name, by_year = {}, {}, {}, {}, {}
    short_reads = []

    for office_id, (label, chamber) in offices.items():
        print(f"\nFetching {label} (legacy office {office_id})...")
        rows, expected = fetch_office(office_id, label)

        # totalItems is trustworthy on this API, so a mismatch means a page
        # genuinely failed rather than the count being unreliable (which is the
        # situation on PeachFile). Record it and fail the run at the end.
        if expected is not None and len(rows) != expected:
            short_reads.append(f"{label}: got {len(rows)}, expected {expected}")

        for r in rows:
            fid = r.get("filerEntityId")
            if fid is None:
                continue
            fid = str(fid)
            cid = r.get("electionCycleId")

            # Records are keyed by filer AND cycle, not filer alone. One committee
            # runs across several cycles under the same filerEntityId — Justin
            # Laster (62394) has both a 2022 row at $226.75 raised and a 2026 row
            # at $0 — so keying on the filer id alone silently kept whichever row
            # happened to be read last and discarded the rest. The per-cycle
            # figures are the entire point of this file.
            rec_id = f"{fid}:{cid}" if cid is not None else fid

            year = cycle_year(r.get("electionCycleName"))
            district = r.get("districtName")
            entry = {
                "recordId":      rec_id,
                "filerEntityId": fid,
                "electionCycleId": cid,
                "source":        "legacy",   # never joinable to a PeachFile id
                "filerName":     r.get("filerName"),
                "ballotName":    r.get("ballotFullName"),
                "firstName":     r.get("candidateFirstName"),
                "lastName":      r.get("candidateLastName"),
                "middleName":    r.get("candidateMiddleName") or None,
                "office":        label,
                "officeId":      office_id,
                "district":      str(district) if district not in (None, "") else None,
                "party":         r.get("politicalPartyCode"),
                "totalRaised":   r.get("totalContributions"),
                "totalSpent":    r.get("totalExpenditures"),
                "cashOnHand":    r.get("cashOnHand"),
                "electionCycle": r.get("electionCycleName"),
                "cycleYear":     year,
            }
            # Only carry fields that say something — see the same reasoning in
            # generate_ga_campaign_finance.py. Repeating constants across
            # thousands of records inflates a file the pages download.
            if r.get("committeeName"):
                entry["committeeName"] = r["committeeName"]
            if r.get("isTerminated"):
                entry["terminated"] = True
            filers[rec_id] = entry

            # Dedupe on insert. The API returns the same record on several rows
            # (one per associated election); appending blindly put a single filer
            # in a bucket up to eight times when this was first written for
            # PeachFile, which made one candidate look like a seat full of
            # same-named filers to anything checking for ambiguity.
            def bucket_add(target, key):
                b = target.setdefault(key, [])
                if rec_id not in b:
                    b.append(rec_id)

            if chamber and entry["district"]:
                bucket_add(by_seat, f"{chamber}-{entry['district']}")
            else:
                bucket_add(by_office, label)
            if year:
                bucket_add(by_year, str(year))

            key = norm_name(entry["firstName"], entry["lastName"], entry["filerName"])
            if key:
                # A list, not a single id: unlike the PeachFile file this spans
                # many cycles, so one person legitimately holds several records.
                b = by_name.setdefault(key, [])
                if rec_id not in b:
                    b.append(rec_id)

        print(f"  {len(rows)} rows"
              + (f" (expected {expected})" if expected is not None else ""))
        time.sleep(DELAY)

    if not filers:
        print("Error: no filers collected — aborting rather than overwriting good data",
              file=sys.stderr)
        sys.exit(1)

    if short_reads:
        print("\nError: incomplete reads — refusing to publish a truncated dataset:",
              file=sys.stderr)
        for s in short_reads:
            print(f"  - {s}", file=sys.stderr)
        sys.exit(1)

    years = sorted(y for y in by_year if y)
    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "source":      "Georgia Ethics Commission legacy records search "
                           "(api-recordsearch.ethics.ga.gov)",
            "sourceUrl":   "https://recordsearch.ethics.ga.gov/public/cf/publiccandidate",
            "coverage":    "Filings through 2025-12-31. Filings from 2026-01-01 onward are "
                           "in PeachFile; see ga-campaign-finance.json.",
            "joinNote":    "filerEntityId is NOT shared with ga-campaign-finance.json — the "
                           "id ranges overlap numerically but refer to different entities. "
                           "Join on office + district + normalized name.",
            "keyNote":     "`filers` is keyed by recordId ('<filerEntityId>:<electionCycleId>'), "
                           "one record per committee per election cycle. A single filerEntityId "
                           "spans multiple cycles with different totals.",
            "cycleYears":  years,
            "offices":     sorted({label for label, _ in offices.values()}),
            "count":       len(filers),
        },
        "filers":           filers,
        "bySeat":           by_seat,
        "byOffice":         by_office,
        "byCycleYear":      by_year,
        "byNormalizedName": by_name,
    }

    os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(outfile) // 1024
    print(f"\nDone. {len(filers)} filers | {size_kb} KB -> {outfile}")
    print(f"  cycle years: {', '.join(years)}")
    print(f"  seats covered: {len(by_seat)} | statewide offices: {len(by_office)}")


if __name__ == "__main__":
    main()
