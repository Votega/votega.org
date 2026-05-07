#!/usr/bin/env python3
"""
Generate ga-member-votes.json from the legis.ga.gov public REST API.
No authentication required — these are public legislative records.

API endpoints discovered via ATLJoeReed/ga-legislation-scraper:
  GET /api/sessions                       → list all sessions, find isCurrent
  GET /api/Vote/list/1/{session}          → house vote summaries for session
  GET /api/Vote/list/2/{session}          → senate vote summaries for session
  GET /api/Vote/detail/{vote_id}          → full roll call + bill info

Output: assets/data/ga-member-votes.json
  {
    "metadata": { generatedAt, sessionId, sessionDescription, totalVotes },
    "votes": { "<vote_id>": { name, caption, date, bill, legislationId, yea, nay } },
    "memberVotes": { "<legis_ga_gov_id>": [{ "voteId": int, "vote": "Yea"|"Nay"|... }] }
  }

The memberVotes key is the numeric legis.ga.gov member ID (legisGaGovId field in ga-members.json).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

BASE        = "https://www.legis.ga.gov"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-member-votes.json"
DELAY       = 0.5   # seconds between API calls — be respectful to the public server

VOTE_LABELS = {0: "Nay", 1: "Yea", 2: "Not Voting", 3: "Excused"}


def fetch(url, retries=3):
    print(f"  GET {url[:110]}...")
    req = urllib.request.Request(url, headers={
        "Accept":     "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; votega.org/1.0)",
        "Referer":    "https://www.legis.ga.gov/",
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} on attempt {attempt}/{retries}")
            if attempt < retries:
                time.sleep(DELAY * attempt)
        except Exception as e:
            print(f"  Error on attempt {attempt}/{retries}: {e}")
            if attempt < retries:
                time.sleep(DELAY * attempt)
    return None


def get_current_session():
    sessions = fetch(f"{BASE}/api/sessions")
    if not sessions:
        print("Error: could not fetch sessions list")
        sys.exit(1)
    for s in sessions:
        if s.get("isCurrent"):
            return s["id"], s.get("description", "")
    # Fallback: use the session with the highest ID
    s = max(sessions, key=lambda x: x["id"])
    print(f"  Warning: no current session flagged — using highest ID: {s['id']}")
    return s["id"], s.get("description", "")


def get_vote_list(session_id, chamber_int):
    result = fetch(f"{BASE}/api/Vote/list/{chamber_int}/{session_id}")
    return result if isinstance(result, list) else []


def get_vote_detail(vote_id):
    return fetch(f"{BASE}/api/Vote/detail/{vote_id}")


def main():
    print("Fetching current Georgia legislative session...")
    session_id, session_desc = get_current_session()
    print(f"  Session {session_id}: {session_desc}")

    print("Fetching House vote list...")
    house_votes = get_vote_list(session_id, 1)
    time.sleep(DELAY)
    print(f"  {len(house_votes)} House votes")

    print("Fetching Senate vote list...")
    senate_votes = get_vote_list(session_id, 2)
    time.sleep(DELAY)
    print(f"  {len(senate_votes)} Senate votes")

    all_vote_items = house_votes + senate_votes
    total = len(all_vote_items)
    print(f"\nFetching {total} vote details (est. {total * DELAY / 60:.1f} min)...")

    votes_meta   = {}   # str(vote_id) -> summary dict
    member_votes = {}   # str(legis_ga_gov_member_id) -> list of {voteId, vote}
    skipped      = 0

    for i, vote_summary in enumerate(all_vote_items, 1):
        vote_id = vote_summary.get("id")
        if not vote_id:
            continue

        time.sleep(DELAY)
        detail = get_vote_detail(vote_id)

        if not detail:
            print(f"  [{i}/{total}] Skipped vote {vote_id} (no data)")
            skipped += 1
            continue

        legislation = detail.get("legislation") or []
        bill        = legislation[0].get("description", "") if legislation else ""
        leg_id      = legislation[0].get("legislationId") if legislation else None

        votes_meta[str(vote_id)] = {
            "name":          vote_summary.get("name", ""),
            "caption":       vote_summary.get("caption", ""),
            "date":          vote_summary.get("date", ""),
            "bill":          bill,
            "legislationId": leg_id,
            "yea":           vote_summary.get("yea", 0),
            "nay":           vote_summary.get("nay", 0),
        }

        for record in (detail.get("votes") or []):
            member     = record.get("member") or {}
            member_id  = str(member.get("id", ""))
            if not member_id:
                continue
            vote_label = VOTE_LABELS.get(record.get("memberVoted"), "Unknown")
            member_votes.setdefault(member_id, []).append({
                "voteId": vote_id,
                "vote":   vote_label,
            })

        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] processed, {skipped} skipped so far")

    output = {
        "metadata": {
            "generatedAt":        datetime.now().isoformat(),
            "sessionId":          session_id,
            "sessionDescription": session_desc,
            "totalVotes":         len(votes_meta),
            "skipped":            skipped,
        },
        "votes":       votes_meta,
        "memberVotes": member_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        # Use compact separators — this file can get large
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(votes_meta)} votes · {len(member_votes)} members · {size_kb} KB → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
