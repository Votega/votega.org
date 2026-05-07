#!/usr/bin/env python3
"""
Generate ga-member-votes.json from the Open States API (Georgia).
Requires OPENSTATES_API_KEY environment variable.

NOTE: legis.ga.gov's own REST API returns 401 on direct calls — it requires
browser-level authentication that can't be replicated with urllib. Open States
is the preferred source since we already integrate with it for member data and
member vote records use OCD person IDs that match ga-members.json directly.

Output: assets/data/ga-member-votes.json
  {
    "metadata": { generatedAt, session, sessionName, totalVotes },
    "votes": { "<vote_event_id>": { motionText, date, bill, billId, result } },
    "memberVotes": { "<ocd-person/...>": [{ "voteId": str, "vote": "Yea"|"Nay"|... }] }
  }

The memberVotes key is the OCD person ID — matches the id field in ga-members.json.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

API_KEY         = os.environ.get('OPENSTATES_API_KEY')
BASE_URL        = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
OUTPUT_FILE     = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-member-votes.json"

VOTE_MAP = {
    "yes":        "Yea",
    "no":         "Nay",
    "other":      "Not Voting",
    "not voting": "Not Voting",
    "excused":    "Excused",
    "absent":     "Excused",
}


def fetch_url(url, retries=3, backoff=5):
    print(f"  Fetching: {url[:120]}...")
    req = urllib.request.Request(url, headers={
        'X-API-Key':  API_KEY or '',
        'Accept':     'application/json',
        'User-Agent': 'votega.org/1.0',
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            print(f"  HTTP {e.code}: {e.reason} — {body[:200]}")
            if e.code >= 500 and attempt < retries:
                time.sleep(backoff)
                continue
            return None
        except Exception as e:
            print(f"  Error on attempt {attempt}/{retries}: {e}")
            if attempt < retries:
                time.sleep(backoff)
                continue
            return None
    return None


def get_current_session():
    """Return (identifier, name) for Georgia's most recent primary session."""
    data = fetch_url(
        f"{BASE_URL}/jurisdictions/{GA_JURISDICTION}?include=legislative_sessions"
    )
    if not data:
        return None, None
    sessions = data.get('legislative_sessions', [])
    # Prefer sessions classified as 'primary'; fall back to all
    primary = [s for s in sessions if s.get('classification') == 'primary']
    pool    = primary or sessions
    pool.sort(key=lambda s: s.get('start_date', ''), reverse=True)
    s = pool[0]
    return s.get('identifier'), s.get('name')


def get_all_votes(session_identifier):
    """Fetch all vote events for the session (paginated), including individual votes."""
    all_votes = []
    page      = 1
    per_page  = 20  # Open States votes endpoint maximum

    while True:
        params = urllib.parse.urlencode([
            ('jurisdiction', GA_JURISDICTION),
            ('session',      session_identifier),
            ('include',      'votes'),
            ('per_page',     per_page),
            ('page',         page),
        ])
        data = fetch_url(f"{BASE_URL}/votes?{params}")
        if not data or 'results' not in data:
            print(f"  Warning: no results on page {page}")
            break

        results = data['results']
        all_votes.extend(results)

        pagination = data.get('pagination', {})
        max_page   = pagination.get('max_page', 1)
        print(f"  Page {page}/{max_page}: {len(results)} vote events ({len(all_votes)} total)")

        if page >= max_page:
            break
        page += 1
        time.sleep(0.3)

    return all_votes


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    print("Fetching current Georgia legislative session from Open States...")
    session_id, session_name = get_current_session()
    if not session_id:
        print("Error: could not determine current session")
        sys.exit(1)
    print(f"  Session: {session_id} ({session_name})")

    print("Fetching vote events...")
    vote_events = get_all_votes(session_id)
    print(f"  {len(vote_events)} total vote events fetched")

    votes_meta   = {}
    member_votes = {}

    for event in vote_events:
        event_id = event.get('id', '')
        bill     = (event.get('bill') or {})
        bill_num = bill.get('identifier', '')
        bill_id  = bill.get('id', '') or event.get('bill_id', '')

        votes_meta[event_id] = {
            "motionText": event.get('motion_text', ''),
            "date":       event.get('start_date', ''),
            "bill":       bill_num,
            "billId":     bill_id,
            "result":     event.get('result', ''),
        }

        for v in (event.get('votes') or []):
            voter_id = v.get('voter_id', '')
            if not voter_id:
                continue
            option     = (v.get('option') or '').lower()
            vote_label = VOTE_MAP.get(option, 'Other')
            member_votes.setdefault(voter_id, []).append({
                "voteId": event_id,
                "vote":   vote_label,
            })

    if not votes_meta:
        print("Warning: no vote data found. Open States may not yet have GA votes for this session.")

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "session":     session_id,
            "sessionName": session_name,
            "totalVotes":  len(votes_meta),
        },
        "votes":       votes_meta,
        "memberVotes": member_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(votes_meta)} votes · {len(member_votes)} members · {size_kb} KB → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
