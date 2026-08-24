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

from lib.http import fetch_bytes, fetch_json

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
    # Delegates to lib.http: this previously made a single attempt with no
    # retry, so one transient Congress.gov 5xx emptied the vote file and the
    # workflow committed it. See CODEBASE-REVIEW-2026-08-18.md 2.4.
    return fetch_json(
        url,
        headers={"Accept": "application/json"},
        redact=CONGRESS_API_KEY,
        label=safe,
    )


def fetch_raw(url, label=""):
    """Fetch raw bytes from URL. Returns None on 404 or error.

    A 404 here is an expected, uninteresting outcome (a roll-call file that
    does not exist yet), so it stays unlogged via quiet_statuses. Everything
    else now follows the shared 429/5xx retry policy instead of giving up on
    the first attempt.
    """
    return fetch_bytes(url, label=label or url[:80], quiet_statuses=(404,))


def sitting_ga_bioguides(members_file):
    """Set of bioguideIds for the current GA delegation, from current-members.json.
    Used to tell a benign stale vote record (a member who left mid-Congress but
    whose recorded votes remain) apart from a real drop — a *sitting* member with
    no votes. See CODEBASE-REVIEW-2026-08-18.md finding 5.5."""
    try:
        with open(members_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None  # unknown -> skip the check rather than emit a wrong count
    return {
        m["bioguideId"] for m in data.get("members", [])
        if m.get("state") == "Georgia" and m.get("bioguideId")
    }


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
    question    = txt("vote-question")
    result_text = txt("vote-result")

    yea = nay = 0
    for totals in root.findall(".//totals-by-vote"):
        for child in totals:
            t = (child.tag or "").lower().replace("-", "_")
            try:
                val = int(child.text or 0)
            except (ValueError, TypeError):
                continue
            if t in ("yea_total", "yes_total", "aye_total"):
                yea += val
            elif t in ("nay_total", "no_total"):
                nay += val

    # Whole-chamber party breakdown, straight from the Clerk's <totals-by-party>
    # blocks (Republican / Democratic / Independent). "other" folds present +
    # not-voting so the Yea/Nay/other shape matches the GA member page.
    party_tally = {}
    for tbp in root.findall(".//totals-by-party"):
        party = (tbp.findtext("party") or "").strip()
        if not party:
            continue
        def _pint(tag, node=tbp):
            try:
                return int(node.findtext(tag) or 0)
            except (ValueError, TypeError):
                return 0
        party_tally[party] = {
            "yea":   _pint("yea-total"),
            "nay":   _pint("nay-total"),
            "other": _pint("present-total") + _pint("not-voting-total"),
        }

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
        "partyTally": party_tally or None,
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
    yea       = int(txt(".//count/yeas") or 0)   # Senate XML nests these under <count>
    nay       = int(txt(".//count/nays") or 0)

    # Senate XML has no party totals, so tally every member's vote by party.
    # Party letters (D/R/I/ID) map to the same names the House XML and the GA
    # member page use.
    PARTY_NAME = {"D": "Democratic", "R": "Republican", "I": "Independent", "ID": "Independent"}
    party_tally = {}
    for member in root.findall(".//member"):
        pletter = (member.findtext("party") or "").strip().upper()
        pname   = PARTY_NAME.get(pletter, pletter or "Other")
        label   = VOTE_MAP.get((member.findtext("vote_cast") or "").strip(), "Other")
        bucket  = party_tally.setdefault(pname, {"yea": 0, "nay": 0, "other": 0})
        if label == "Yea":
            bucket["yea"] += 1
        elif label == "Nay":
            bucket["nay"] += 1
        else:
            bucket["other"] += 1

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
        "partyTally": party_tally or None,
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

    # Reconcile vote records against the sitting delegation so a real drop is
    # visible in metadata rather than blending into the benign stale case.
    with_votes = set(member_votes)
    sitting = sitting_ga_bioguides(MEMBERS_FILE)
    vote_stats = {}
    if sitting is not None:
        sitting_with_votes = sitting & with_votes
        stale = with_votes - sitting          # departed members, votes linger
        missing = sitting - with_votes        # sitting members with NO votes = a real drop
        vote_stats = {
            "sittingDelegation":       len(sitting),
            "sittingMembersWithVotes": len(sitting_with_votes),
            "staleVoteRecords":        len(stale),
        }
        if missing:
            print(f"  WARNING: {len(missing)} sitting GA member(s) have no vote records: "
                  f"{sorted(missing)}", file=sys.stderr)
            vote_stats["sittingMembersMissingVotes"] = sorted(missing)

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "congress":    CURRENT_CONGRESS,
            "sessionName": f"{CURRENT_CONGRESS}th Congress",
            "source":      "Congress.gov API + Clerk of House + Senate.gov",
            "totalVotes":  len(votes_meta),
            "memberCount": len(member_votes),
            **vote_stats,
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
