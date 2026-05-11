#!/usr/bin/env python3
"""
Generate curated-ga-bill-votes.json from Open States API.
Reads assets/data/curated-ga-bills.json (maintainer-controlled list) and fetches
vote data, party tallies, and bill metadata for each entry.
Requires OPENSTATES_API_KEY environment variable.
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

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"

CURATED_BILLS_FILE = "assets/data/curated-ga-bills.json"
GA_MEMBERS_FILE    = "assets/data/ga-members.json"
OUTPUT_FILE        = sys.argv[1] if len(sys.argv) > 1 else "assets/data/curated-ga-bill-votes.json"


def fetch_url(url, retries=3, backoff=5):
    print(f"  GET {url[:120]}")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                'X-API-Key': API_KEY or '',
                'Accept': 'application/json',
                'User-Agent': 'votega.org/1.0',
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            print(f"  HTTP {e.code}: {e.reason} — {body[:300]}")
            if e.code >= 500 and attempt < retries:
                print(f"  Retrying in {backoff}s ({attempt}/{retries})...")
                time.sleep(backoff)
                continue
            return None
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < retries:
                print(f"  Retrying in {backoff}s ({attempt}/{retries})...")
                time.sleep(backoff)
                continue
            return None
    return None


def build_party_lookup():
    """Return {ocd-person-id: party} from ga-members.json."""
    with open(GA_MEMBERS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    lookup = {m['id']: m['party'] for m in data.get('members', []) if m.get('id')}
    print(f"  Loaded party data for {len(lookup)} members")
    return lookup


def extract_roll_number(motion_text):
    """Parse roll number from 'House Vote #56 - ...' motion text."""
    if not motion_text:
        return None
    m = re.search(r'#(\d+)', motion_text)
    return int(m.group(1)) if m else None


def select_passage_vote(votes, chamber_classification, override_roll=None):
    """
    Select the final passage vote for a chamber from a list of vote events.
    Uses highest roll number to pick the latest passage vote (handles substitute votes).
    override_roll pins to a specific roll number from curated-ga-bills.json voteOverride.
    """
    chamber_votes = [
        v for v in votes
        if (v.get('organization') or {}).get('classification') == chamber_classification
        and v.get('motion_classification') == ['passage']
    ]
    if not chamber_votes:
        return None

    if override_roll is not None:
        for v in chamber_votes:
            if extract_roll_number(v.get('motion_text')) == override_roll:
                return v
        print(f"  WARNING: voteOverride #{override_roll} not found — falling back to auto-detect")

    return max(chamber_votes, key=lambda v: extract_roll_number(v.get('motion_text')) or -1)


def pick_full_text_url(versions):
    """
    Select the As Passed bill text PDF from versions[].
    Prefers a version whose note contains '/AP' (As Passed).
    Falls back to the last version with any PDF link.
    """
    if not versions:
        return ''
    for v in versions:
        note = v.get('note', '')
        if '/AP' in note:
            for link in v.get('links', []):
                if link.get('media_type') == 'application/pdf':
                    return link['url']
    for v in reversed(versions):
        for link in v.get('links', []):
            if link.get('media_type') == 'application/pdf':
                return link['url']
    return ''


def build_vote_record(vote_event, party_lookup):
    """
    Build the standardized vote record for one chamber from a raw Open States vote event.
    Derives partyTally by joining each voter.id against ga-members.json party data.
    """
    party_tally = {
        'Democratic':  {'yea': 0, 'nay': 0, 'other': 0},
        'Republican':  {'yea': 0, 'nay': 0, 'other': 0},
        'Independent': {'yea': 0, 'nay': 0, 'other': 0},
    }
    member_votes = {}

    for pv in vote_event.get('votes', []):
        voter    = pv.get('voter') or {}
        voter_id = voter.get('id')
        option   = pv.get('option', '')  # 'yes', 'no', 'abstain', 'other'

        if voter_id:
            member_votes[voter_id] = option
            party = party_lookup.get(voter_id)
            if party and party in party_tally:
                bucket = 'yea' if option == 'yes' else ('nay' if option == 'no' else 'other')
                party_tally[party][bucket] += 1

    return {
        'rollNumber':  extract_roll_number(vote_event.get('motion_text')),
        'date':        vote_event.get('start_date', ''),
        'motionText':  vote_event.get('motion_text', ''),
        'result':      vote_event.get('result', ''),
        'partyTally':  party_tally,
        'memberVotes': member_votes,
    }


def fetch_bill(entry, party_lookup):
    """Fetch and process one curated bill entry. Returns a bill record dict or None."""
    session    = entry['session']
    identifier = entry['identifier']

    params = urllib.parse.urlencode([
        ('jurisdiction', GA_JURISDICTION),
        ('session',      session),
        ('identifier',   identifier),
        ('include',      'votes'),
        ('include',      'abstracts'),
        ('include',      'versions'),
    ])
    data = fetch_url(f"{BASE_URL}/bills?{params}")

    if not data or not data.get('results'):
        print(f"  WARNING: Not found — session={session!r} identifier={identifier!r}")
        print(f"           Verify the session string matches Open States exactly.")
        return None

    bill = data['results'][0]
    all_votes = bill.get('votes', [])
    overrides = entry.get('voteOverride') or {}

    house_event  = select_passage_vote(all_votes, 'lower', overrides.get('house'))
    senate_event = select_passage_vote(all_votes, 'upper', overrides.get('senate'))

    votes = {}
    if house_event:
        votes['house']  = build_vote_record(house_event,  party_lookup)
    if senate_event:
        votes['senate'] = build_vote_record(senate_event, party_lookup)

    if not votes:
        print(f"  WARNING: No passage votes found for {identifier} ({session})")

    abstracts = bill.get('abstracts', [])
    summary   = entry.get('summaryOverride') or (abstracts[0].get('abstract', '') if abstracts else '')

    # Construct openstatesUrl from bill identifier (strip spaces for URL)
    openstates_url = f"https://openstates.org/ga/bills/{session}/{identifier.replace(' ', '')}/"

    print(f"  OK — {len(votes)} chamber vote(s)  |  summary: {'override' if entry.get('summaryOverride') else 'API'}")

    return {
        'id':           bill.get('id', ''),
        'session':      session,
        'identifier':   identifier,
        'title':        bill.get('title', ''),
        'summary':      summary,
        'status':       bill.get('latest_action_description', ''),
        'statusDate':   bill.get('latest_action_date', ''),
        'openstatesUrl': openstates_url,
        'fullTextUrl':  pick_full_text_url(bill.get('versions', [])),
        'votes':        votes,
    }


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    with open(CURATED_BILLS_FILE, encoding='utf-8') as f:
        curated = json.load(f)
    bill_list = curated.get('ga', [])
    print(f"Processing {len(bill_list)} curated bills...\n")

    print("Loading member party data...")
    party_lookup = build_party_lookup()

    results = []
    failed  = []
    for entry in bill_list:
        label = entry.get('_name') or entry['identifier']
        print(f"\n--- {label} ({entry['identifier']}, {entry['session']}) ---")
        record = fetch_bill(entry, party_lookup)
        if record:
            results.append(record)
        else:
            failed.append(entry['identifier'])
        time.sleep(7)  # Open States rate limit is 10 req/min — 7s keeps well under it

    output = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'source':      'Open States API',
            'count':       len(results),
        },
        'bills': results,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(results)} bill records to {OUTPUT_FILE}")
    if failed:
        print(f"WARNING: {len(failed)} bill(s) not fetched: {', '.join(failed)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
