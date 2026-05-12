#!/usr/bin/env python3
"""
Quick diagnostic: fetch one GA bill and one roll call from LegiScan,
print the raw response structure so we can see what 'votes' looks like.
Run: LEGISCAN_API_KEY=your_key python scripts/debug_legiscan_rollcall.py
"""

import json
import os
import sys
import urllib.request
import urllib.parse

API_KEY  = os.environ.get('LEGISCAN_API_KEY')
BASE_URL = "https://api.legiscan.com/"


def legiscan(op, params=None):
    query = {"key": API_KEY, "op": op}
    if params:
        query.update(params)
    url = BASE_URL + "?" + urllib.parse.urlencode(query)
    print(f"  > {op}({params or {}})")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    if not API_KEY:
        print("Error: LEGISCAN_API_KEY not set")
        sys.exit(1)

    # 1. Get current GA session
    data = legiscan("getSessionList", {"state": "GA"})
    sessions = data.get("sessions", [])
    current = next((s for s in sessions if s.get("sine_die") == 0), None) or \
              max(sessions, key=lambda s: s.get("year_start", 0))
    session_id = current["session_id"]
    print(f"\nSession: {session_id} — {current.get('session_name')}\n")

    # 2. Get master list and pick the first bill that's past introduction
    data = legiscan("getMasterList", {"state": "GA"})
    master = data.get("masterlist", {})
    bills = [v for k, v in master.items() if k.isdigit() and v.get("bill_id") and v.get("status", 0) > 1]
    if not bills:
        print("No actionable bills found")
        sys.exit(1)
    bill = bills[0]
    print(f"Using bill: {bill.get('number')} (bill_id={bill.get('bill_id')}, status={bill.get('status')})\n")

    # 3. Fetch bill details to get a roll_call_id
    data = legiscan("getBill", {"id": bill["bill_id"]})
    bill_detail = data.get("bill", {})
    rc_list = bill_detail.get("votes") or []
    if not rc_list:
        print("This bill has no roll calls — try a different one")
        sys.exit(1)
    rc_summary = rc_list[0]
    rc_id = rc_summary.get("roll_call_id")
    print(f"Roll call ID: {rc_id}\n")

    # 4. Fetch the roll call and print full structure
    data = legiscan("getRollCall", {"id": rc_id})
    rc = data.get("roll_call", {})

    print("=== roll_call keys ===")
    print(list(rc.keys()))

    print("\n=== votes field ===")
    raw_votes = rc.get("votes")
    print(f"Type: {type(raw_votes).__name__}")
    print(f"Truthy: {bool(raw_votes)}")
    if isinstance(raw_votes, list):
        print(f"Length: {len(raw_votes)}")
        if raw_votes:
            print(f"First entry: {json.dumps(raw_votes[0], indent=2)}")
    elif isinstance(raw_votes, dict):
        print(f"Keys (first 5): {list(raw_votes.keys())[:5]}")
        first_val = next(iter(raw_votes.values()), None)
        if first_val:
            print(f"First value: {json.dumps(first_val, indent=2)}")
    else:
        print(f"Value: {raw_votes!r}")

    print(f"\n=== Summary ===")
    print(f"  yea={rc.get('yea')}  nay={rc.get('nay')}  passed={rc.get('passed')}")
    print(f"  date={rc.get('date')}  desc={rc.get('desc')}")


if __name__ == "__main__":
    main()
