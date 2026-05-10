#!/usr/bin/env python3
"""
Generate ga-member-votes.json from LegiScan API (Georgia).
Requires LEGISCAN_API_KEY environment variable.

LegiScan API flow:
  1. getSessionList(state=GA)     → find current session_id
  2. getSessionPeople(session_id) → map LegiScan people_id to names
  3. getMasterListRaw(session_id) → get all bills in one call (with change_hash)
  4. getBill(bill_id)             → get roll_call_ids (only for bills past introduction)
  5. getRollCall(roll_call_id)    → full member vote record

ID bridging:
  LegiScan uses numeric people_id; ga-members.json uses OCD person IDs.
  We match on normalized full name. memberVotes is keyed by OCD person ID
  so ga-member.html can look up by member.id without any changes.
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

API_KEY      = os.environ.get('LEGISCAN_API_KEY')
BASE_URL     = "https://api.legiscan.com/"
OUTPUT_FILE  = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-member-votes.json"
MEMBERS_FILE = sys.argv[2] if len(sys.argv) > 2 else "assets/data/ga-members.json"
DELAY        = 2.0  # LegiScan API manual p.7: allow adequate time between requests to avoid cache hits

# LegiScan vote_id codes
VOTE_TEXT_MAP = {1: "Yea", 2: "Nay", 3: "Not Voting", 4: "Absent", 5: "Excused"}


def legiscan(op, params=None, retries=3):
    query = {"key": API_KEY, "op": op}
    if params:
        query.update(params)
    url = BASE_URL + "?" + urllib.parse.urlencode(query)
    print(f"  {op}({', '.join(f'{k}={v}' for k, v in (params or {}).items())})...")
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("status") == "ERROR":
                msg = (data.get("alert") or {}).get("message", "unknown error")
                print(f"  LegiScan API error: {msg}")
                return None
            return data
        except Exception as e:
            print(f"  Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(DELAY * attempt)
    return None


def normalize_name_tokens(name):
    """Return a frozenset of lowercase alpha tokens from a name string.
    Handles both 'Last, First' and 'First Last' formats."""
    name = name.lower()
    if "," in name:
        last, first = name.split(",", 1)
        name = first.strip() + " " + last.strip()
    return frozenset(re.sub(r"[^a-z\s]", "", name).split())


def build_name_index(members):
    """Map frozenset-of-name-tokens → OCD person ID."""
    return {normalize_name_tokens(m["name"]): m["id"] for m in members}


def match_member(legiscan_name, name_index):
    tokens = normalize_name_tokens(legiscan_name)
    # Exact token-set match
    if tokens in name_index:
        return name_index[tokens]
    # Partial: at least 2 tokens overlap (catches middle name / suffix differences)
    best, best_score = None, 1
    for indexed_tokens, ocd_id in name_index.items():
        overlap = len(tokens & indexed_tokens)
        if overlap > best_score:
            best, best_score = ocd_id, overlap
    return best


def get_current_session(state="GA"):
    data = legiscan("getSessionList", {"state": state})
    if not data:
        return None, None
    sessions = data.get("sessions", [])
    # sine_die == 0 means session is still active
    current = next((s for s in sessions if s.get("sine_die") == 0), None)
    if not current:
        current = max(sessions, key=lambda s: s.get("year_start", 0))
    return current["session_id"], current.get("session_name", "")


def get_session_people(session_id):
    # getSessionPeople requires a higher API plan tier — may return "Invalid session id"
    data = legiscan("getSessionPeople", {"session_id": session_id})
    if not data:
        return []
    return data.get("sessionpeople", {}).get("people", [])


def get_master_list(state="GA"):
    # getMasterListRaw takes state=, not session_id=
    data = legiscan("getMasterListRaw", {"state": state})
    if not data:
        return []
    master = data.get("masterlist", {})
    # Numeric string keys are bills; "0" is session metadata — filter by bill_id presence
    return [v for k, v in master.items() if k.isdigit() and v.get("bill_id")]


def get_bill(bill_id):
    data = legiscan("getBill", {"id": bill_id})
    if not data:
        return None
    return data.get("bill")


def get_roll_call(roll_call_id):
    data = legiscan("getRollCall", {"id": roll_call_id})
    if not data:
        return None
    return data.get("roll_call")


def main():
    if not API_KEY:
        print("Error: LEGISCAN_API_KEY environment variable not set")
        sys.exit(1)

    # Load ga-members.json for name → OCD ID bridging
    if not os.path.exists(MEMBERS_FILE):
        print(f"Error: {MEMBERS_FILE} not found — run update-ga-members workflow first")
        sys.exit(1)
    with open(MEMBERS_FILE, encoding="utf-8") as f:
        members_data = json.load(f)
    name_index = build_name_index(members_data.get("members", []))
    print(f"Loaded {len(name_index)} GA members for name matching")

    print("\nFetching current Georgia session from LegiScan...")
    session_id, session_name = get_current_session()
    if not session_id:
        print("Error: could not determine current session")
        sys.exit(1)
    print(f"  Session {session_id}: {session_name}")
    time.sleep(DELAY)

    print("\nFetching session people...")
    session_people = get_session_people(session_id)
    # Build LegiScan people_id → OCD person ID via name matching
    # If getSessionPeople is unavailable (plan restriction), we fall back to
    # matching names on-the-fly from roll call vote records instead.
    legiscan_to_ocd = {}
    if session_people:
        unmatched = []
        for person in session_people:
            lid    = person.get("people_id")
            name   = person.get("name", "")
            ocd_id = match_member(name, name_index)
            if ocd_id:
                legiscan_to_ocd[lid] = ocd_id
            else:
                unmatched.append(name)
        print(f"  Matched {len(legiscan_to_ocd)}/{len(session_people)} members by name")
        if unmatched:
            print(f"  Unmatched ({len(unmatched)}): {', '.join(unmatched)}")
    else:
        print("  getSessionPeople unavailable — will match names from roll call records")
    time.sleep(DELAY)

    print("\nFetching master bill list...")
    bills = get_master_list()
    # Log status distribution to understand what values LegiScan is returning
    status_dist = {}
    for b in bills:
        s = b.get("status", "missing")
        status_dist[s] = status_dist.get(s, 0) + 1
    print(f"  Status distribution: {sorted(status_dist.items())}")

    # Sample last_action values to find a usable filter
    sample_actions = [b.get("last_action", "") for b in bills[:10]]
    print(f"  Sample last_action values: {sample_actions}")

    # Filter: prefer status > 1, but fall back to any bill with a last_action
    # (LegiScan may set status=0 for all bills after session ends)
    actionable = [b for b in bills if b.get("status", 0) > 1]
    if not actionable:
        print("  No bills with status > 1 — falling back to bills with last_action set")
        actionable = [b for b in bills if b.get("last_action")]
    print(f"  {len(bills)} total bills, {len(actionable)} actionable (will fetch details)")
    time.sleep(DELAY)

    votes_meta        = {}
    member_votes      = {}
    bills_fetched     = 0
    roll_calls_fetched = 0

    print("\nFetching bill details and roll calls...")
    for i, bill_summary in enumerate(actionable, 1):
        bill_id = bill_summary.get("bill_id")
        if not bill_id:
            continue

        time.sleep(DELAY)
        bill = get_bill(bill_id)
        bills_fetched += 1
        if not bill:
            continue

        bill_number = bill.get("bill_number", "")
        bill_url    = bill.get("state_link", "")

        for rc_summary in (bill.get("votes") or []):
            rc_id = rc_summary.get("roll_call_id")
            if not rc_id or str(rc_id) in votes_meta:
                continue

            time.sleep(DELAY)
            rc = get_roll_call(rc_id)
            roll_calls_fetched += 1
            if not rc:
                continue

            votes_meta[str(rc_id)] = {
                "bill":       bill_number,
                "billUrl":    bill_url,
                "motionText": rc.get("desc", ""),
                "date":       rc.get("date", ""),
                "yea":        rc.get("yea", 0),
                "nay":        rc.get("nay", 0),
                "result":     "Pass" if rc.get("passed") == 1 else "Fail",
            }

            for v in (rc.get("votes") or []):
                lid    = v.get("people_id")
                ocd_id = legiscan_to_ocd.get(lid)
                # Lazy name match if getSessionPeople was unavailable
                if not ocd_id and lid:
                    name = v.get("name", "")
                    if name:
                        ocd_id = match_member(name, name_index)
                        if ocd_id:
                            legiscan_to_ocd[lid] = ocd_id
                if not ocd_id:
                    continue
                vote_label = VOTE_TEXT_MAP.get(v.get("vote_id"), v.get("vote_text", "Other"))
                member_votes.setdefault(ocd_id, []).append({
                    "voteId": str(rc_id),
                    "vote":   vote_label,
                })

        if i % 25 == 0 or i == len(actionable):
            print(f"  [{i}/{len(actionable)}] bills · {roll_calls_fetched} roll calls · {len(member_votes)} members with votes")

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "session":     session_id,
            "sessionName": session_name,
            "source":      "LegiScan",
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
