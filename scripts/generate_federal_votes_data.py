#!/usr/bin/env python3
"""
Generate federal-member-votes.json from LegiScan API (US Congress, GA delegation only).
Requires LEGISCAN_API_KEY environment variable.

LegiScan API flow:
  1. getSessionList(state=US)     → find current Congress session_id
  2. getSessionPeople(session_id) → filter to GA delegation (state=GA)
  3. congress-legislators YAML    → build VoteSmart ID → bioguideId map
  4. getMasterListRaw(session_id) → all federal bills; filter to status=4 (signed)
  5. getBill(bill_id)             → get roll_call_ids for signed bills
  6. getRollCall(roll_call_id)    → full member votes; keep only GA members

Output: assets/data/federal-member-votes.json
  memberVotes keyed by bioguideId — matches member.html's lookup.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import yaml
from datetime import datetime

API_KEY          = os.environ.get('LEGISCAN_API_KEY')
BASE_URL         = "https://api.legiscan.com/"
OUTPUT_FILE      = sys.argv[1] if len(sys.argv) > 1 else "assets/data/federal-member-votes.json"
MEMBERS_FILE     = sys.argv[2] if len(sys.argv) > 2 else "assets/data/current-members.json"
LEGISLATORS_BASE = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"
DELAY            = 0.5

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
                print(f"  LegiScan error: {msg}")
                return None
            return data
        except Exception as e:
            print(f"  Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(DELAY * attempt)
    return None


def fetch_yaml(url):
    print(f"  Fetching YAML: {url[:80]}...")
    req = urllib.request.Request(url, headers={"User-Agent": "votega.org/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return yaml.safe_load(r.read().decode("utf-8"))


def build_votesmart_index():
    """Return {str(votesmart_id): bioguideId} from congress-legislators YAML."""
    legislators = fetch_yaml(f"{LEGISLATORS_BASE}/legislators-current.yaml")
    index = {}
    for leg in (legislators or []):
        ids      = leg.get("id", {})
        vsmart   = ids.get("votesmart")
        bioguide = ids.get("bioguide")
        if vsmart and bioguide:
            index[str(vsmart)] = bioguide
    print(f"  VoteSmart index: {len(index)} entries")
    return index


def build_name_index(members):
    """Return {normalized_name: bioguideId} from current-members.json."""
    index = {}
    for m in members:
        raw = m.get("directOrderName") or f"{m.get('firstName','')} {m.get('lastName','')}".strip()
        key = re.sub(r"[^a-z\s]", "", raw.lower()).strip()
        if key:
            index[key] = m["bioguideId"]
    return index


def normalize_name(name):
    """Normalize 'Last, First' or 'First Last' to comparable lowercase tokens."""
    name = name.lower().strip()
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return re.sub(r"[^a-z\s]", "", name).strip()


def get_current_session():
    data = legiscan("getSessionList", {"state": "US"})
    if not data:
        return None, None
    sessions = data.get("sessions", [])
    current  = next((s for s in sessions if s.get("sine_die") == 0), None)
    if not current:
        current = max(sessions, key=lambda s: s.get("year_start", 0))
    return current["session_id"], current.get("session_name", "")


def get_session_people(session_id):
    data = legiscan("getSessionPeople", {"session_id": session_id})
    if not data:
        return []
    return data.get("sessionpeople", {}).get("people", [])


def get_master_list(session_id):
    data = legiscan("getMasterListRaw", {"session_id": session_id})
    if not data:
        return []
    master = data.get("masterlist", {})
    return [v for k, v in master.items() if k.isdigit() and v.get("bill_id")]


def get_bill(bill_id):
    data = legiscan("getBill", {"id": bill_id})
    return data.get("bill") if data else None


def get_roll_call(roll_call_id):
    data = legiscan("getRollCall", {"id": roll_call_id})
    return data.get("roll_call") if data else None


def main():
    if not API_KEY:
        print("Error: LEGISCAN_API_KEY environment variable not set")
        sys.exit(1)

    # Load current-members.json for name-based fallback matching
    ga_members_by_name = {}
    if os.path.exists(MEMBERS_FILE):
        with open(MEMBERS_FILE, encoding="utf-8") as f:
            members_data = json.load(f)
        ga_members = [m for m in members_data.get("members", [])
                      if (m.get("state") or m.get("stateName") or "") in ("Georgia", "GA")]
        ga_members_by_name = build_name_index(ga_members)
        print(f"Loaded {len(ga_members)} GA federal members for fallback name matching")

    print("\nBuilding VoteSmart → bioguideId index from congress-legislators...")
    votesmart_index = build_votesmart_index()
    time.sleep(DELAY)

    print("\nFetching current US Congress session from LegiScan...")
    session_id, session_name = get_current_session()
    if not session_id:
        print("Error: could not determine current session")
        sys.exit(1)
    print(f"  Session {session_id}: {session_name}")
    time.sleep(DELAY)

    print("\nFetching session people — filtering to GA delegation...")
    all_people    = get_session_people(session_id)
    ga_people     = [p for p in all_people if p.get("state", "").upper() == "GA"]
    print(f"  {len(ga_people)} GA members found (of {len(all_people)} total)")
    time.sleep(DELAY)

    # Build LegiScan people_id → bioguideId map
    legiscan_to_bioguide = {}
    unmatched = []
    for person in ga_people:
        lid      = str(person.get("people_id", ""))
        vsmart   = str(person.get("votesmart") or "")
        name     = person.get("name", "")
        bioguide = votesmart_index.get(vsmart)
        if not bioguide:
            # Fallback: name match against current-members.json
            norm    = normalize_name(name)
            bioguide = ga_members_by_name.get(norm)
        if bioguide:
            legiscan_to_bioguide[lid] = bioguide
        else:
            unmatched.append(name)

    print(f"  Matched {len(legiscan_to_bioguide)}/{len(ga_people)} GA members to bioguideId")
    if unmatched:
        print(f"  Unmatched: {', '.join(unmatched)}")

    print("\nFetching master bill list...")
    all_bills  = get_master_list(session_id)
    # Only signed-into-law bills (status 4)
    signed     = [b for b in all_bills if b.get("status", 0) == 4]
    print(f"  {len(all_bills)} total bills, {len(signed)} signed into law")
    time.sleep(DELAY)

    votes_meta        = {}
    member_votes      = {}
    roll_calls_fetched = 0

    print(f"\nFetching bill details and roll calls for {len(signed)} signed bills...")
    for i, bill_summary in enumerate(signed, 1):
        bill_id = bill_summary.get("bill_id")
        if not bill_id:
            continue

        time.sleep(DELAY)
        bill = get_bill(bill_id)
        if not bill:
            continue

        bill_number = bill.get("bill_number", "")
        bill_url    = bill.get("state_link", "")
        bill_title  = bill.get("title", "")

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
                "title":      bill_title,
                "motionText": rc.get("desc", ""),
                "date":       rc.get("date", ""),
                "yea":        rc.get("yea", 0),
                "nay":        rc.get("nay", 0),
                "result":     "Pass" if rc.get("passed") == 1 else "Fail",
            }

            for v in (rc.get("votes") or []):
                lid      = str(v.get("people_id", ""))
                bioguide = legiscan_to_bioguide.get(lid)
                if not bioguide:
                    continue
                vote_label = VOTE_TEXT_MAP.get(v.get("vote_id"), v.get("vote_text", "Other"))
                member_votes.setdefault(bioguide, []).append({
                    "voteId": str(rc_id),
                    "vote":   vote_label,
                })

        if i % 25 == 0 or i == len(signed):
            print(f"  [{i}/{len(signed)}] bills · {roll_calls_fetched} roll calls · {len(member_votes)} GA members with votes")

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
    print(f"\nDone. {len(votes_meta)} votes · {len(member_votes)} GA members · {size_kb} KB → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
