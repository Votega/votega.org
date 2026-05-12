#!/usr/bin/env python3
"""
Generate ga-member-votes.json from Open States API (Georgia).
Requires OPENSTATES_API_KEY environment variable.

Open States API flow:
  1. Paginate GET /bills?jurisdiction=GA&session=2025_26&include=votes
  2. For each bill, collect vote events where motion_classification == ['passage']
  3. Each vote event's votes[] has voter.id (OCD person ID) — no name matching needed
     since ga-members.json already uses OCD person IDs.

To update for a new session: change GA_SESSION below.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

API_KEY      = os.environ.get('OPENSTATES_API_KEY')
BASE_URL     = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
GA_SESSION   = "2025_26"
SESSION_NAME = "2025-2026 Regular Session"
OUTPUT_FILE  = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-member-votes.json"

DELAY = 7  # Open States free tier: 10 req/min — 7s keeps safely under

VOTE_MAP = {
    'yes':        'Yea',
    'no':         'Nay',
    'not voting': 'Not Voting',
    'abstain':    'Present',
    'absent':     'Absent',
    'excused':    'Excused',
    'other':      'Other',
}


def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={
        'X-API-Key': API_KEY or '',
        'Accept':    'application/json',
        'User-Agent': 'votega.org/1.0',
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            print(f"  HTTP {e.code}: {body[:200]}")
            if e.code == 429 or e.code >= 500:
                wait = DELAY * attempt * 2
                print(f"  Retrying in {wait}s ({attempt}/{retries})...")
                time.sleep(wait)
                continue
            return None
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < retries:
                time.sleep(DELAY)
                continue
            return None
    return None


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    votes_meta   = {}
    member_votes = {}
    page         = 1
    bills_seen   = 0

    print(f"Fetching GA bills for session {GA_SESSION} (passage votes only)...")

    while True:
        params = urllib.parse.urlencode([
            ('jurisdiction', GA_JURISDICTION),
            ('session',      GA_SESSION),
            ('include',      'votes'),
            ('per_page',     20),
            ('page',         page),
        ])
        data = fetch(f"{BASE_URL}/bills?{params}")
        if not data:
            print(f"  Failed on page {page}, stopping.")
            break

        results = data.get('results', [])
        if not results:
            break

        bills_seen += len(results)

        for bill in results:
            identifier = bill.get('identifier', '')
            title      = bill.get('title', '')
            bill_url   = f"https://openstates.org/ga/bills/{GA_SESSION}/{identifier.replace(' ', '')}/"

            passage_events = [
                ve for ve in bill.get('votes', [])
                if ve.get('motion_classification') == ['passage']
            ]

            for ve in passage_events:
                ve_id = ve.get('id', '')
                if not ve_id or ve_id in votes_meta:
                    continue

                counts = {c['option']: c['value'] for c in ve.get('counts', [])}
                yea    = counts.get('yes', 0)
                nay    = counts.get('no', 0)
                result = 'Pass' if str(ve.get('result', '')).lower() == 'pass' else 'Fail'

                votes_meta[ve_id] = {
                    'bill':       identifier,
                    'billUrl':    bill_url,
                    'title':      title,
                    'motionText': ve.get('motion_text', ''),
                    'date':       ve.get('start_date', ''),
                    'yea':        yea,
                    'nay':        nay,
                    'result':     result,
                }

                for pv in ve.get('votes', []):
                    voter    = pv.get('voter') or {}
                    voter_id = voter.get('id')
                    if not voter_id:
                        continue
                    option     = pv.get('option', '').lower()
                    vote_label = VOTE_MAP.get(option, 'Other')
                    member_votes.setdefault(voter_id, []).append({
                        'voteId': ve_id,
                        'vote':   vote_label,
                    })

        pagination  = data.get('pagination', {})
        total_pages = pagination.get('max_page', 1)
        print(f"  Page {page}/{total_pages} — {bills_seen} bills, {len(votes_meta)} passage votes, {len(member_votes)} members")

        if page >= total_pages:
            break
        page += 1
        time.sleep(DELAY)

    output = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'session':     GA_SESSION,
            'sessionName': SESSION_NAME,
            'source':      'Open States API',
            'totalVotes':  len(votes_meta),
        },
        'votes':       votes_meta,
        'memberVotes': member_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(votes_meta)} passage votes · {len(member_votes)} members · {size_kb} KB -> {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
