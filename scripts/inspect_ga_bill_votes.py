#!/usr/bin/env python3
"""
Spot-check Open States bill + vote data for Georgia.
Finds the most recent GA bill with recorded votes and prints:
  - motion_classification on each vote event
  - voter.id format (OCD person ID?)
  - abstracts (summary) structure
  - versions (full text) structure
"""

import json
import os
import sys
import urllib.request
import urllib.parse

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"


def fetch(url):
    req = urllib.request.Request(url, headers={
        'X-API-Key': API_KEY,
        'Accept': 'application/json',
        'User-Agent': 'votega.org/diagnostic',
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY not set")
        sys.exit(1)

    # Step 1 — find recent GA bills that have votes
    print("=== Searching for recent GA bills with votes ===")
    params = urllib.parse.urlencode([
        ('jurisdiction', GA_JURISDICTION),
        ('sort', 'latest_action_desc'),
        ('per_page', 20),
        ('include', 'votes'),
    ])
    data = fetch(f"{BASE_URL}/bills?{params}")
    bills = data.get('results', [])
    print(f"Fetched {len(bills)} bills")

    # Find the first one that has at least one vote event
    target = None
    for b in bills:
        if b.get('votes'):
            target = b
            break

    if not target:
        print("No bills with votes found in first 20 results — try a broader search")
        sys.exit(1)

    bill_id = target['id']
    print(f"\nUsing bill: {target.get('identifier')} — {target.get('title', '')[:80]}")
    print(f"  OCD bill ID: {bill_id}")
    print(f"  Session: {target.get('legislative_session')}")
    print(f"  Status: {target.get('latest_action_description')}")

    # Step 2 — fetch full bill with all includes
    print("\n=== Fetching full bill record ===")
    params2 = urllib.parse.urlencode([
        ('include', 'votes'),
        ('include', 'abstracts'),
        ('include', 'versions'),
    ])
    full = fetch(f"{BASE_URL}/bills/{bill_id}?{params2}")

    # Step 3 — inspect vote events
    votes = full.get('votes', [])
    print(f"\n--- Vote events ({len(votes)} total) ---")
    for i, ve in enumerate(votes[:5]):
        print(f"\nVote event {i+1}:")
        print(f"  motion_text:           {ve.get('motion_text')}")
        print(f"  motion_classification: {ve.get('motion_classification')}")
        print(f"  result:                {ve.get('result')}")
        print(f"  start_date:            {ve.get('start_date')}")
        org = ve.get('organization', {})
        print(f"  organization:          {org.get('name')} ({org.get('classification')})")

        counts = ve.get('counts', [])
        print(f"  counts: {counts}")

        pv_list = ve.get('votes', [])
        print(f"  individual votes: {len(pv_list)} entries")
        for pv in pv_list[:3]:
            voter = pv.get('voter') or {}
            print(f"    option={pv.get('option')!r:10}  voter_name={pv.get('voter_name')!r:25}  voter.id={voter.get('id')!r}")
        if len(pv_list) > 3:
            print(f"    ... ({len(pv_list) - 3} more)")

    # Step 4 — inspect abstracts
    abstracts = full.get('abstracts', [])
    print(f"\n--- Abstracts ({len(abstracts)} total) ---")
    for ab in abstracts[:2]:
        print(f"  abstract: {ab.get('abstract', '')[:200]}")

    # Step 5 — inspect versions
    versions = full.get('versions', [])
    print(f"\n--- Versions ({len(versions)} total) ---")
    for v in versions[:3]:
        print(f"  note={v.get('note')!r}  date={v.get('date')}")
        for link in v.get('links', [])[:2]:
            print(f"    url={link.get('url')}  media_type={link.get('media_type')}")

    print("\n=== Done ===")


if __name__ == '__main__':
    main()
