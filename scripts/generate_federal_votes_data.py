#!/usr/bin/env python3
"""
Generate federal-member-votes.json for GA delegation.

Flow:
  1. Congress.gov API /v3/law/{congress} → enacted public laws
  2. Congress.gov API /v3/bill/.../actions → roll call XML URLs per bill
  3. Clerk of House XML (clerk.house.gov/evs/) → House votes; bioguideId in XML
  4. Senate.gov XML → Senate votes; LIS IDs mapped via congress-legislators YAML

Output: assets/data/federal-member-votes.json
  memberVotes keyed by bioguideId — matches member.html lookup.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
import yaml
from datetime import datetime

CONGRESS_API_KEY  = os.environ.get('CONGRESS_API_KEY')
CONGRESS_API_BASE = "https://api.congress.gov/v3"
LEGISLATORS_BASE  = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"

OUTPUT_FILE  = sys.argv[1] if len(sys.argv) > 1 else "assets/data/federal-member-votes.json"
MEMBERS_FILE = sys.argv[2] if len(sys.argv) > 2 else "assets/data/current-members.json"

CURRENT_CONGRESS = 119
API_DELAY = 0.5   # Congress.gov API (rate-limited)
XML_DELAY = 0.3   # Static XML files from Clerk/Senate (no rate limit)

# Normalize House and Senate vote text to consistent labels
VOTE_MAP = {
    "Yea": "Yea", "Yes": "Yea", "Aye": "Yea",
    "Nay": "Nay", "No": "Nay",
    "Not Voting": "Not Voting", "Present": "Not Voting",
    "Absent": "Absent", "Excused": "Absent",
}

# Pretty bill type labels for display
TYPE_LABEL = {
    "hr": "H.R.", "s": "S.",
    "hjres": "H.J.Res.", "sjres": "S.J.Res.",
    "hconres": "H.Con.Res.", "sconres": "S.Con.Res.",
    "hres": "H.Res.", "sres": "S.Res.",
}

# Congress.gov URL slug per bill type
TYPE_SLUG = {
    "hr": "house-bill", "s": "senate-bill",
    "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution", "sres": "senate-resolution",
}


def congress_api(path, params=None):
    """Fetch JSON from Congress.gov API."""
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


def fetch_raw(url, label=""):
    """Fetch raw bytes from URL. Returns None on 404 or error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "votega.org/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  HTTP {e.code} fetching {label or url[:80]}")
        return None
    except Exception as e:
        print(f"  Error fetching {label or url[:80]}: {e}")
        return None


def build_lis_to_bioguide():
    """Return {lis_id: bioguideId} from congress-legislators YAML (senators only)."""
    raw = fetch_raw(f"{LEGISLATORS_BASE}/legislators-current.yaml", "legislators-current.yaml")
    if not raw:
        print("  Warning: could not fetch legislators YAML — Senate LIS mapping will be empty")
        return {}
    legislators = yaml.safe_load(raw.decode("utf-8")) or []
    index = {}
    for leg in legislators:
        ids = leg.get("id", {})
        lis = ids.get("lis")
        bioguide = ids.get("bioguide")
        if lis and bioguide:
            index[str(lis)] = bioguide
    print(f"  LIS→bioguide map: {len(index)} entries")
    return index


def get_enacted_bills():
    """
    Paginate /v3/law/{congress} for all public laws in the current Congress.
    Falls back to scanning bill list if the law endpoint returns nothing.
    Returns list of bill dicts (type, number, title, url).
    """
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
        print(f"  {len(bills)} enacted bills fetched so far...")
        if len(page) < 250:
            break
        offset += 250
        time.sleep(API_DELAY)

    if bills:
        print(f"  Found {len(bills)} enacted bills via /law/{CURRENT_CONGRESS}")
        return bills

    # Fallback: iterate each bill type and filter to those with a laws entry
    print("  /law endpoint returned nothing — scanning bill types for enacted legislation...")
    for bill_type in ("hr", "s", "hjres", "sjres", "hconres", "sconres"):
        offset = 0
        while True:
            data = congress_api(f"/bill/{CURRENT_CONGRESS}/{bill_type}", {"offset": offset})
            if not data:
                break
            page = data.get("bills", [])
            if not page:
                break
            bills.extend(b for b in page if b.get("laws"))
            if len(page) < 250:
                break
            offset += 250
            time.sleep(API_DELAY)
        time.sleep(API_DELAY)

    print(f"  Found {len(bills)} enacted bills via bill-list fallback")
    return bills


def get_roll_call_urls(bill_type, bill_number):
    """
    Fetch /v3/bill/{congress}/{type}/{number}/actions and extract roll call XML URLs.
    Returns list of dicts: {url, chamber, rollNumber, date}
    """
    data = congress_api(f"/bill/{CURRENT_CONGRESS}/{bill_type.lower()}/{bill_number}/actions")
    if not data:
        return []

    actions = data.get("actions", [])
    if isinstance(actions, dict):
        actions = actions.get("item", [])
    if not isinstance(actions, list):
        return []

    roll_calls = []
    for action in actions:
        # API returns recordedVotes as a list or a single dict
        rvs = action.get("recordedVotes") or action.get("recordedVote")
        if not rvs:
            continue
        if isinstance(rvs, dict):
            rvs = [rvs]
        for rv in (rvs or []):
            url = (rv.get("url") or "").strip()
            if not url:
                continue
            roll_calls.append({
                "url":        url,
                "chamber":    rv.get("chamber", ""),
                "rollNumber": rv.get("rollNumber", ""),
                "date":       rv.get("date") or action.get("actionDate", ""),
            })
    return roll_calls


def url_to_key(url):
    """
    Convert XML URL to a short, stable vote key.
      House:  clerk.house.gov/evs/2025/roll024.xml  → H2025_0024
      Senate: senate.gov/.../vote_119_1_00024.xml   → S119_1_00024
    """
    m = re.search(r"/evs/(\d{4})/roll(\d+)\.xml", url)
    if m:
        return f"H{m.group(1)}_{int(m.group(2)):04d}"
    m = re.search(r"vote_(\d+)_(\d+)_(\d+)\.xml", url)
    if m:
        return f"S{m.group(1)}_{m.group(2)}_{int(m.group(3)):05d}"
    # Fallback
    return re.sub(r"[^a-zA-Z0-9_]", "_", url)[-30:]


MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

def normalize_date(raw):
    """Normalize various date formats to YYYY-MM-DD."""
    if not raw:
        return ""
    # "16-Jan-2025"
    m = re.match(r"(\d{1,2})-([A-Za-z]+)-(\d{4})", raw)
    if m:
        mon = MONTH_MAP.get(m.group(2).lower(), "00")
        return f"{m.group(3)}-{mon}-{int(m.group(1)):02d}"
    # "January 21, 2025" or "January 21 2025"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        mon = MONTH_MAP.get(m.group(1).lower()[:3], "00")
        return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"
    # Already ISO or partial ISO — return as-is (truncate to date portion)
    return raw[:10]


def parse_house_xml(xml_bytes, bill_label, bill_url, bill_title):
    """
    Parse Clerk of House roll call XML.
    Returns (vote_meta, {bioguideId: vote_label}) for GA members only.
    bioguideId is in the name-id attribute; state="GA" filters to GA delegation.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return None, {}

    meta = root.find(".//vote-metadata")
    if meta is None:
        return None, {}

    def txt(tag):
        el = meta.find(tag)
        return (el.text or "").strip() if el is not None else ""

    action_date = txt("action-date")
    question    = txt("question")
    result_text = txt("vote-result")

    yea = nay = 0
    for totals in root.findall(".//totals-by-vote"):
        for child in totals:
            t   = (child.tag or "").lower().replace("-", "_")
            val = int(child.text or 0)
            if t in ("yea_total", "yes_total", "aye_total"):
                yea += val
            elif t in ("nay_total", "no_total"):
                nay += val

    vote_meta = {
        "bill":       bill_label,
        "billUrl":    bill_url,
        "title":      bill_title,
        "motionText": question,
        "date":       normalize_date(action_date),
        "yea":        yea,
        "nay":        nay,
        "chamber":    "House",
        "result":     "Pass" if "pass" in result_text.lower() else "Fail",
    }

    ga_votes = {}
    for rv in root.findall(".//recorded-vote"):
        leg = rv.find("legislator")
        if leg is None:
            continue
        if (leg.get("state") or "").upper() != "GA":
            continue
        bioguide  = (leg.get("name-id") or "").strip()
        v_el      = rv.find("vote")
        vote_text = (v_el.text or "").strip() if v_el is not None else ""
        label     = VOTE_MAP.get(vote_text, vote_text or "Other")
        if bioguide:
            ga_votes[bioguide] = label

    return vote_meta, ga_votes


def parse_senate_xml(xml_bytes, bill_label, bill_url, bill_title, lis_to_bioguide):
    """
    Parse Senate.gov roll call XML.
    Returns (vote_meta, {bioguideId: vote_label}) for GA senators only.
    Uses lis_to_bioguide map to convert LIS member IDs.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return None, {}

    def txt(path):
        el = root.find(path)
        return (el.text or "").strip() if el is not None else ""

    question  = txt(".//question")
    result    = txt(".//vote_result")
    vote_date = txt(".//vote_date")
    yea       = int(txt(".//count_yeas") or 0)
    nay       = int(txt(".//count_nays") or 0)

    vote_meta = {
        "bill":       bill_label,
        "billUrl":    bill_url,
        "title":      bill_title,
        "motionText": question,
        "date":       normalize_date(vote_date),
        "yea":        yea,
        "nay":        nay,
        "chamber":    "Senate",
        "result":     "Pass" if any(w in result.lower() for w in ("passed", "agreed", "confirmed")) else "Fail",
    }

    ga_votes = {}
    for member in root.findall(".//member"):
        state = (member.findtext("state") or "").strip().upper()
        if state != "GA":
            continue
        lis_id    = (member.findtext("lis_member_id") or "").strip()
        vote_cast = (member.findtext("vote_cast") or "").strip()
        label     = VOTE_MAP.get(vote_cast, vote_cast or "Other")
        bioguide  = lis_to_bioguide.get(lis_id)
        if bioguide:
            ga_votes[bioguide] = label
        elif lis_id:
            print(f"    Warning: no bioguide for GA senator LIS ID {lis_id}")

    return vote_meta, ga_votes


def bill_url(bill_type, bill_number):
    slug = TYPE_SLUG.get(bill_type.lower(), bill_type.lower())
    return f"https://www.congress.gov/bill/{CURRENT_CONGRESS}th-congress/{slug}/{bill_number}"


def main():
    if not CONGRESS_API_KEY:
        print("Error: CONGRESS_API_KEY environment variable not set")
        sys.exit(1)

    print("Building LIS→bioguide senator ID map from congress-legislators...")
    lis_to_bioguide = build_lis_to_bioguide()
    time.sleep(API_DELAY)

    print(f"\nFetching enacted public laws for {CURRENT_CONGRESS}th Congress...")
    enacted_bills = get_enacted_bills()
    print(f"  Total enacted: {len(enacted_bills)}")

    if not enacted_bills:
        print("Warning: No enacted bills found — check Congress.gov API or try again later")

    votes_meta   = {}
    member_votes = {}
    seen_urls    = set()

    print(f"\nFetching roll calls for {len(enacted_bills)} enacted bills...")
    for i, bill in enumerate(enacted_bills, 1):
        bill_type   = (bill.get("type") or "").lower()
        bill_number = str(bill.get("number") or "")
        bill_title  = (bill.get("title") or "").strip()
        prefix      = TYPE_LABEL.get(bill_type, bill_type.upper())
        bill_label  = f"{prefix} {bill_number}"
        bill_page   = bill_url(bill_type, bill_number)

        if i % 20 == 0 or i == len(enacted_bills):
            print(f"  [{i}/{len(enacted_bills)}] {bill_label} · {len(votes_meta)} roll calls · {len(member_votes)} GA members")

        time.sleep(API_DELAY)
        rc_refs = get_roll_call_urls(bill_type, bill_number)

        for rc_ref in rc_refs:
            xml_url = rc_ref["url"]
            if not xml_url or xml_url in seen_urls:
                continue
            seen_urls.add(xml_url)

            vote_key = url_to_key(xml_url)
            if vote_key in votes_meta:
                continue

            time.sleep(XML_DELAY)
            xml_bytes = fetch_raw(xml_url, xml_url.split("/")[-1])
            if not xml_bytes:
                continue

            is_senate = "senate.gov" in xml_url
            if is_senate:
                vote_meta, ga_votes = parse_senate_xml(
                    xml_bytes, bill_label, bill_page, bill_title, lis_to_bioguide
                )
            else:
                vote_meta, ga_votes = parse_house_xml(
                    xml_bytes, bill_label, bill_page, bill_title
                )

            if not vote_meta:
                continue

            votes_meta[vote_key] = vote_meta

            for bioguide, vote_label in ga_votes.items():
                member_votes.setdefault(bioguide, []).append({
                    "voteId": vote_key,
                    "vote":   vote_label,
                })

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "congress":    CURRENT_CONGRESS,
            "sessionName": f"{CURRENT_CONGRESS}th Congress",
            "source":      "Congress.gov API + Clerk of House + Senate.gov",
            "totalVotes":  len(votes_meta),
        },
        "votes":       votes_meta,
        "memberVotes": member_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(votes_meta)} votes · {len(member_votes)} GA members · {size_kb} KB → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
