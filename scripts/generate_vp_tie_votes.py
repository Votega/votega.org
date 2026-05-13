#!/usr/bin/env python3
"""
Generate vp-tie-votes.json — Vice President tie-breaking votes in the Senate.

The VP (as President of the Senate) can cast a tie-breaking vote when the Senate
is deadlocked 50-50. This script identifies those votes by:

  1. Fetching the Senate vote list XML for each session of the current Congress.
  2. Filtering to votes where yeas == nays (potential tie-breaking votes).
  3. Fetching the detail XML for each candidate vote.
  4. Checking for a <tie_breaker> element — only present when the VP actually voted.

Source: senate.gov roll call XML (public, no API key required).
Output: assets/data/vp-tie-votes.json
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime

CURRENT_CONGRESS = 119
SESSIONS         = [1, 2]   # Check both sessions; missing ones are skipped gracefully
XML_DELAY        = 0.3      # seconds between requests

OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/vp-tie-votes.json"

SENATE_BASE     = "https://www.senate.gov/legislative/LIS"
VOTE_LIST_URL   = f"{SENATE_BASE}/roll_call_lists/vote_menu_{{congress}}_{{session}}.xml"
VOTE_DETAIL_URL = f"{SENATE_BASE}/roll_call_votes/vote{{congress}}{{session}}/vote_{{congress}}_{{session}}_{{vote_number}}.xml"
VOTE_PAGE_URL   = "https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{vote_number}.htm"

ACTION_LABELS = {
    'On the Nomination':          'Confirmation',
    'On Passage of the Bill':     'Passage',
    'On the Motion to Proceed':   'Motion to Proceed',
    'On the Motion to Discharge': 'Motion to Discharge',
    'On the Motion to Table':     'Motion to Table',
    'On the Amendment':           'Amendment',
    'On the Point of Order':      'Point of Order',
}

# Boilerplate prefixes to strip from documentTitle for cleaner summaries
_DOC_PREFIX_RE = re.compile(
    r'^(a\s+bill|a\s+joint\s+resolution|a\s+resolution|a\s+concurrent\s+resolution)\s+to\s+',
    re.IGNORECASE,
)


def build_summary(vote):
    """
    Return a plain descriptive summary of what the vote was about — no action prefix.
    Used as a secondary line beneath the vote title and meta row.
    Returns None if no meaningful description is available.
    """
    question  = vote.get('question', '')
    title     = vote.get('title', '')
    doc_title = (vote.get('documentTitle') or '').strip()

    # Nominations: strip the "Confirmation:" prefix for a clean one-liner
    if question == 'On the Nomination':
        return re.sub(r'^Confirmation:\s*', '', title).strip() or None

    # Use documentTitle when it has real substance
    if doc_title and len(doc_title) > 15:
        subject = _DOC_PREFIX_RE.sub('', doc_title).rstrip('.')
        subject = subject[0].upper() + subject[1:] if subject else subject
        # Truncate very long official titles
        if len(subject) > 120:
            subject = subject[:117].rsplit(' ', 1)[0] + '…'
        return subject

    return None


MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def fetch_raw(url, label=""):
    """Fetch bytes from URL. Returns None on 404 or error."""
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


def normalize_date(raw):
    """Normalize Senate date strings to YYYY-MM-DD."""
    if not raw:
        return ""
    raw = raw.strip()
    # "July 15, 2025,  09:20 PM" or "July 15, 2025"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        mon = MONTH_MAP.get(m.group(1).lower()[:3], "00")
        return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"
    # "15-Jul-2025"
    m = re.match(r"(\d{1,2})-([A-Za-z]+)-(\d{4})", raw)
    if m:
        mon = MONTH_MAP.get(m.group(2).lower(), "00")
        return f"{m.group(3)}-{mon}-{int(m.group(1)):02d}"
    return raw[:10]


def get_tied_votes_from_list(congress, session):
    """
    Fetch the vote list XML for a session and return vote numbers where yeas == nays.
    Returns list of zero-padded vote number strings (e.g. "00392").
    """
    url = VOTE_LIST_URL.format(congress=congress, session=session)
    print(f"  Fetching vote list: vote_menu_{congress}_{session}.xml")
    raw = fetch_raw(url, f"vote_menu_{congress}_{session}.xml")
    if not raw:
        print(f"  Session {session} not found — skipping")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return []

    tied = []
    for vote in root.findall(".//vote"):
        tally = vote.find("vote_tally")
        if tally is None:
            continue
        try:
            yeas = int(tally.findtext("yeas") or 0)
            nays = int(tally.findtext("nays") or 0)
        except (ValueError, TypeError):
            continue
        if yeas > 0 and yeas == nays:
            num = (vote.findtext("vote_number") or "").strip()
            if num:
                tied.append(num)

    print(f"  Session {session}: {root.find('.//congress_year') is not None and 'found' or 'found'} "
          f"{len(root.findall('.//vote'))} votes, {len(tied)} tied")
    return tied


def parse_vote_detail(raw, congress, session, vote_number):
    """
    Parse a Senate vote detail XML.
    Returns a vote dict if the VP cast a tie-breaking vote, else None.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  XML parse error for vote {vote_number}: {e}")
        return None

    tb = root.find(".//tie_breaker")
    if tb is None:
        return None  # VP did not vote — 50-50 that failed without VP

    vp_vote = (tb.findtext("tie_breaker_vote") or "").strip()
    if not vp_vote:
        return None

    def txt(path):
        el = root.find(path)
        return (el.text or "").strip() if el is not None else ""

    yeas = int(txt(".//count/yeas") or 0)
    nays = int(txt(".//count/nays") or 0)

    doc = root.find(".//document")
    doc_type   = txt(".//document/document_type")
    doc_number = txt(".//document/document_number")
    doc_label  = f"{doc_type} {doc_number}".strip() if (doc_type or doc_number) else ""
    doc_title  = txt(".//document/document_title")

    # Short title fallback
    if not doc_title:
        doc_title = txt(".//document/document_short_title")

    page_url = VOTE_PAGE_URL.format(
        congress=congress, session=session, vote_number=vote_number
    )

    vote = {
        "voteNumber":    vote_number,
        "congress":      congress,
        "session":       session,
        "date":          normalize_date(txt(".//vote_date")),
        "question":      txt(".//question"),
        "title":         txt(".//vote_title"),
        "resultText":    txt(".//vote_result_text"),
        "result":        txt(".//vote_result"),
        "vpVote":        vp_vote,
        "yeas":          yeas,
        "nays":          nays,
        "document":      doc_label,
        "documentTitle": doc_title,
        "url":           page_url,
    }
    vote["summary"] = build_summary(vote)
    return vote


def main():
    all_votes = []

    for session in SESSIONS:
        print(f"\nScanning Congress {CURRENT_CONGRESS}, Session {session}...")
        tied_numbers = get_tied_votes_from_list(CURRENT_CONGRESS, session)

        if not tied_numbers:
            continue

        print(f"  Fetching detail XML for {len(tied_numbers)} tied votes...")
        for vote_number in tied_numbers:
            padded = vote_number.zfill(5)
            url = VOTE_DETAIL_URL.format(
                congress=CURRENT_CONGRESS,
                session=session,
                vote_number=padded,
            )
            time.sleep(XML_DELAY)
            raw = fetch_raw(url, f"vote_{CURRENT_CONGRESS}_{session}_{padded}.xml")
            if not raw:
                continue

            result = parse_vote_detail(raw, CURRENT_CONGRESS, session, padded)
            if result:
                print(f"    VP tie-breaker found: vote {padded} — {result['vpVote']} — {result['question'][:60]}")
                all_votes.append(result)
            else:
                print(f"    vote {padded}: tied tally but no VP vote (failed 50-50)")

    # Sort chronologically
    all_votes.sort(key=lambda v: v["date"])

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "congress":    CURRENT_CONGRESS,
            "source":      "Senate.gov roll call XML",
            "count":       len(all_votes),
        },
        "votes": all_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(all_votes)} VP tie-breaking votes -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
