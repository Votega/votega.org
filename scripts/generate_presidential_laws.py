#!/usr/bin/env python3
"""
Generate presidential-laws.json — bills signed into law since the start of the current term.

Uses the Congress.gov /v3/law/{congress} endpoint (same source as the federal votes pipeline).
Filters to laws whose latest action date falls on or after the term start date.

Output: assets/data/presidential-laws.json
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

CONGRESS_API_KEY  = os.environ.get('CONGRESS_API_KEY')
CONGRESS_API_BASE = "https://api.congress.gov/v3"

CURRENT_CONGRESS = 119
TERM_START       = "2025-01-20"   # Update when a new administration begins
API_DELAY        = 0.5

OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/presidential-laws.json"

# Human-readable bill type labels
TYPE_LABEL = {
    "hr":      "H.R.",
    "s":       "S.",
    "hjres":   "H.J.Res.",
    "sjres":   "S.J.Res.",
    "hconres": "H.Con.Res.",
    "sconres": "S.Con.Res.",
    "hres":    "H.Res.",
    "sres":    "S.Res.",
}

# Congress.gov URL slugs per bill type
TYPE_SLUG = {
    "hr":      "house-bill",
    "s":       "senate-bill",
    "hjres":   "house-joint-resolution",
    "sjres":   "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
    "hres":    "house-resolution",
    "sres":    "senate-resolution",
}


def congress_api(path, params=None):
    """Fetch JSON from Congress.gov API with pagination support."""
    query = {"format": "json", "api_key": CONGRESS_API_KEY, "limit": 250}
    if params:
        query.update(params)
    url = f"{CONGRESS_API_BASE}{path}?{urllib.parse.urlencode(query)}"
    safe = url.replace(CONGRESS_API_KEY, "***") if CONGRESS_API_KEY else url
    print(f"  API: {safe[:120]}...")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "votega.org/1.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def build_congress_url(bill_type, bill_number):
    slug = TYPE_SLUG.get(bill_type.lower(), bill_type.lower())
    return f"https://www.congress.gov/bill/{CURRENT_CONGRESS}th-congress/{slug}/{bill_number}"


def fetch_all_laws():
    """Paginate /v3/law/{congress} and return every enacted bill."""
    bills = []
    offset = 0
    while True:
        data = congress_api(f"/law/{CURRENT_CONGRESS}", {"offset": offset})
        if not data:
            break
        page = data.get("bills", [])
        if not page:
            break
        bills.extend(page)
        print(f"  {len(bills)} laws fetched so far...")
        if len(page) < 250:
            break
        offset += 250
        time.sleep(API_DELAY)
    return bills


def extract_law(bill):
    """
    Build a clean law record from a Congress.gov bill object.
    Returns None if the law was signed before the term start date.
    """
    bill_type   = (bill.get("type") or "").lower()
    bill_number = str(bill.get("number") or "")
    title       = (bill.get("title") or "").strip()

    latest_action = bill.get("latestAction") or {}
    signing_date  = (latest_action.get("actionDate") or "").strip()
    action_text   = (latest_action.get("text") or "").strip()

    # Filter to current term
    if signing_date < TERM_START:
        return None

    bill_label = f"{TYPE_LABEL.get(bill_type, bill_type.upper())} {bill_number}"
    congress_url = build_congress_url(bill_type, bill_number)

    # Public law number — may be a list or single item depending on API version
    laws_field = bill.get("laws") or []
    if isinstance(laws_field, dict):
        laws_field = [laws_field]
    public_law_number = None
    for law in laws_field:
        if isinstance(law, dict) and (law.get("type") or "").lower() == "public":
            public_law_number = law.get("number")
            break

    # Policy area — present on some endpoints, absent on others
    policy_area = None
    pa = bill.get("policyArea")
    if isinstance(pa, dict):
        policy_area = pa.get("name")
    elif isinstance(pa, str):
        policy_area = pa

    origin_chamber = (bill.get("originChamber") or bill.get("originChamberCode") or "").strip()

    return {
        "billLabel":       bill_label,
        "type":            bill_type,
        "number":          bill_number,
        "title":           title,
        "signingDate":     signing_date,
        "actionText":      action_text,
        "publicLawNumber": public_law_number,
        "policyArea":      policy_area,
        "originChamber":   origin_chamber,
        "congressUrl":     congress_url,
    }


def main():
    if not CONGRESS_API_KEY:
        print("Error: CONGRESS_API_KEY environment variable not set")
        sys.exit(1)

    print(f"Fetching enacted public laws for {CURRENT_CONGRESS}th Congress...")
    all_bills = fetch_all_laws()
    print(f"  Total from API: {len(all_bills)}")

    laws = []
    skipped = 0
    for bill in all_bills:
        record = extract_law(bill)
        if record:
            laws.append(record)
        else:
            skipped += 1

    # Newest first
    laws.sort(key=lambda l: l["signingDate"], reverse=True)

    print(f"  Signed since {TERM_START}: {len(laws)} laws ({skipped} pre-term skipped)")

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "congress":    CURRENT_CONGRESS,
            "termStart":   TERM_START,
            "source":      "Congress.gov API",
            "count":       len(laws),
        },
        "laws": laws,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"Done. {len(laws)} laws -> {OUTPUT_FILE} ({size_kb} KB)")


if __name__ == "__main__":
    main()
