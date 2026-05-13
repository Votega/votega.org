#!/usr/bin/env python3
"""
Generate scotus-decisions.json — Supreme Court decisions with per-justice vote breakdowns.

Primary source: Oyez.org API (free, no key, CORS-open).
  - Case list by term: https://api.oyez.org/cases?per_page=100&filter=term:{year}
  - Case detail (with votes): https://api.oyez.org/cases/{term}/{docket}

CourtListener search is used to enrich cases with opinion page links where available.
  - Search: https://www.courtlistener.com/api/rest/v4/search/?type=o&court=scotus

Output: assets/data/scotus-decisions.json
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

TERMS       = ["2024", "2025"]   # Terms to include; add new term each October
API_DELAY   = 0.25

OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/scotus-decisions.json"

OYEZ_BASE = "https://api.oyez.org"
CL_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"


def fetch_json(url, label=""):
    """Fetch and parse JSON from a URL. Returns None on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "votega.org/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  HTTP {e.code}: {label or url[:80]}")
        return None
    except Exception as e:
        print(f"  Error fetching {label or url[:80]}: {e}")
        return None


def unix_to_date(ts):
    """Convert Unix timestamp to YYYY-MM-DD string."""
    if not ts:
        return None
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


def get_event_date(timeline, event_name):
    """Extract the first date for a named event from an Oyez timeline list."""
    for event in (timeline or []):
        if event.get("event") == event_name:
            dates = event.get("dates") or []
            if dates:
                return unix_to_date(dates[0])
    return None


def fetch_term_cases(term):
    """
    Fetch the case list for a given SCOTUS term from Oyez.
    Returns list of basic case dicts.
    """
    url = f"{OYEZ_BASE}/cases?per_page=100&filter=term:{term}"
    print(f"  Fetching {term} term cases from Oyez...")
    data = fetch_json(url, f"oyez term {term}")
    if not data:
        return []
    print(f"  Found {len(data)} cases in {term} term")
    return data


def fetch_case_detail(term, docket):
    """Fetch full case detail (including decisions/votes) from Oyez."""
    # Docket numbers sometimes have trailing spaces
    docket = docket.strip()
    url = f"{OYEZ_BASE}/cases/{term}/{urllib.parse.quote(docket)}"
    return fetch_json(url, f"{term}/{docket}")


def build_cl_index(term):
    """
    Fetch SCOTUS opinion URLs from CourtListener search for a given term.
    Returns dict of {docket_number: courtlistener_url}.
    CourtListener search is public (no auth needed).
    """
    index = {}
    # CourtListener terms roughly map: Oyez "2024" term = Oct 2024 – Jun 2025
    year = int(term)
    date_min = f"{year}-10-01"
    date_max = f"{year + 1}-09-30"
    params = urllib.parse.urlencode({
        "q": "", "type": "o", "order_by": "dateFiled asc",
        "stat_Precedential": "on", "court": "scotus",
        "filed_after": date_min, "filed_before": date_max,
        "page_size": 100,
    })
    url = f"{CL_SEARCH}?{params}"
    print(f"  Fetching CourtListener index for {term} term...")
    data = fetch_json(url, "CourtListener search")
    if not data:
        return index

    for result in (data.get("results") or []):
        docket = (result.get("docketNumber") or "").strip()
        abs_url = result.get("absolute_url") or ""
        if docket and abs_url:
            cl_url = f"https://www.courtlistener.com{abs_url}"
            index[docket] = cl_url

    print(f"  CourtListener: {len(index)} opinions indexed")
    return index


def extract_decision(detail, cl_index):
    """
    Parse an Oyez case detail dict into a clean record.
    Returns None if the case has not been decided yet.
    """
    timeline    = detail.get("timeline") or []
    decided_date = get_event_date(timeline, "Decided")
    if not decided_date:
        return None

    docket = (detail.get("docket_number") or "").strip()
    term   = str(detail.get("term") or "")

    # Per-justice vote breakdown
    decisions_raw = detail.get("decisions") or []
    votes = []
    majority_count  = 0
    minority_count  = 0
    winning_party   = None
    decision_desc   = None
    decision_type   = None

    if decisions_raw:
        dec = decisions_raw[0]
        majority_count = dec.get("majority_vote") or 0
        minority_count = dec.get("minority_vote") or 0
        winning_party  = dec.get("winning_party")
        decision_desc  = dec.get("description") or ""
        decision_type  = dec.get("decision_type") or ""

        for v in (dec.get("votes") or []):
            member = v.get("member") or {}
            votes.append({
                "justiceId":    member.get("identifier") or "",
                "justiceName":  member.get("name") or "",
                "lastName":     member.get("last_name") or "",
                "vote":         v.get("vote") or "",          # "majority" | "minority" | "concurrence" etc.
                "opinionType":  v.get("opinion_type") or "",  # "majority" | "concurrence" | "dissent" | None
            })

    # Written opinion authors and links
    opinions = []
    for wo in (detail.get("written_opinion") or []):
        op_type = (wo.get("type") or {})
        opinions.append({
            "type":      op_type.get("value") or "",
            "label":     op_type.get("label") or "",
            "author":    wo.get("judge_last_name") or wo.get("judge_full_name") or "",
            "justiaUrl": wo.get("justia_opinion_url") or "",
        })

    cl_url = cl_index.get(docket) or cl_index.get(docket.rstrip())

    return {
        "id":           detail.get("ID"),
        "name":         detail.get("name") or "",
        "docketNumber": docket,
        "term":         term,
        "decidedDate":  decided_date,
        "arguedDate":   get_event_date(timeline, "Argued"),
        "description":  detail.get("description") or "",
        "question":     re.sub(r"<[^>]+>", "", detail.get("question") or "").strip(),
        "conclusion":   re.sub(r"<[^>]+>", "", detail.get("conclusion") or "").strip(),
        "winningParty": winning_party,
        "majorityVote": majority_count,
        "minorityVote": minority_count,
        "decisionType": decision_type,
        "decisionDesc": decision_desc,
        "votes":        votes,
        "opinions":     opinions,
        "oyezUrl":      f"https://www.oyez.org/cases/{term}/{docket}",
        "justiaUrl":    detail.get("justia_url") or "",
        "courtListenerUrl": cl_url or "",
    }


def main():
    all_cases = []

    for term in TERMS:
        print(f"\n--- {term} SCOTUS term ---")
        cases_basic = fetch_term_cases(term)
        if not cases_basic:
            print(f"  No cases found for {term} term — skipping")
            continue

        # Build CourtListener index for cross-referencing
        time.sleep(API_DELAY)
        cl_index = build_cl_index(term)

        # Only fetch detail for cases that have a Decided event in basic data
        decided_basic = [
            c for c in cases_basic
            if any(e.get("event") == "Decided" for e in (c.get("timeline") or []))
        ]
        print(f"  Decided cases: {len(decided_basic)} / {len(cases_basic)}")

        for i, case in enumerate(decided_basic, 1):
            docket = (case.get("docket_number") or "").strip()
            if not docket:
                continue

            time.sleep(API_DELAY)
            detail = fetch_case_detail(term, docket)
            if not detail:
                print(f"  [{i}/{len(decided_basic)}] Could not fetch detail for {docket}")
                continue

            record = extract_decision(detail, cl_index)
            if record:
                all_cases.append(record)
                if i % 10 == 0 or i == len(decided_basic):
                    print(f"  [{i}/{len(decided_basic)}] {len(all_cases)} decisions processed")

    # Sort by decided date, most recent first
    all_cases.sort(key=lambda c: c["decidedDate"] or "", reverse=True)

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "terms":       TERMS,
            "source":      "Oyez.org API + CourtListener",
            "count":       len(all_cases),
        },
        "cases": all_cases,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(all_cases)} decisions -> {OUTPUT_FILE} ({size_kb} KB)")


if __name__ == "__main__":
    main()
