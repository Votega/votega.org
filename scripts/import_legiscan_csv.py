#!/usr/bin/env python3
"""
Bootstrap ga-member-votes.json from a LegiScan CSV data dump.
More efficient than API calls for initial or bulk loads.

Usage:
  python scripts/import_legiscan_csv.py <csv_dir> [output_file] [members_file]

  csv_dir:      directory containing bills.csv, people.csv, rollcalls.csv, votes.csv
  output_file:  defaults to assets/data/ga-member-votes.json
  members_file: defaults to assets/data/ga-members.json

ID bridging strategy:
  LegiScan uses numeric people_id; ga-members.json uses OCD person IDs.
  We match via district string (e.g. "HD-137" → House district 137), which is
  a unique, reliable key — more robust than name matching.
"""

import csv
import json
import os
import sys
from datetime import datetime

CSV_DIR      = sys.argv[1] if len(sys.argv) > 1 else "assets/data/legiscan-csv"
OUTPUT_FILE  = sys.argv[2] if len(sys.argv) > 2 else "assets/data/ga-member-votes.json"
MEMBERS_FILE = sys.argv[3] if len(sys.argv) > 3 else "assets/data/ga-members.json"

VOTE_LABEL_MAP = {
    "yea":        "Yea",
    "nay":        "Nay",
    "nv":         "Not Voting",
    "not voting": "Not Voting",
    "absent":     "Absent",
    "excused":    "Excused",
}


def read_csv(filepath):
    with open(filepath, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_district_index(members):
    """Map ('HD'|'SD', district_int) → OCD person ID."""
    index = {}
    for m in members:
        chamber  = m.get("chamber", "")
        district = m.get("district")
        if district is None:
            continue
        try:
            dist_int = int(district)
        except (ValueError, TypeError):
            continue
        prefix = "HD" if "House" in chamber else "SD" if "Senate" in chamber else None
        if prefix:
            index[(prefix, dist_int)] = m["id"]
    return index


def parse_district_key(district_str):
    """Parse 'HD-137' → ('HD', 137) or 'SD-024' → ('SD', 24). Returns None on failure."""
    if not district_str:
        return None
    parts = district_str.upper().strip().split("-")
    if len(parts) != 2:
        return None
    try:
        return (parts[0], int(parts[1]))
    except ValueError:
        return None


def coerce_int(val):
    try:
        return int(val or 0)
    except (ValueError, TypeError):
        return 0


def normalize_date(date_str):
    """Convert M/D/YYYY to YYYY-MM-DD. Passthrough for already-ISO strings."""
    if not date_str:
        return ""
    if "/" in date_str:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    return date_str.strip()


def get_col(row, *candidates):
    """Return first matching column value from a list of candidate column names."""
    for key in candidates:
        if key in row and row[key] is not None:
            return row[key]
    return ""


def main():
    # Validate inputs
    for fname in ["bills.csv", "people.csv", "rollcalls.csv", "votes.csv"]:
        path = os.path.join(CSV_DIR, fname)
        if not os.path.exists(path):
            print(f"Error: {path} not found")
            sys.exit(1)

    if not os.path.exists(MEMBERS_FILE):
        print(f"Error: {MEMBERS_FILE} not found — run update-ga-members workflow first")
        sys.exit(1)

    with open(MEMBERS_FILE, encoding="utf-8") as f:
        members_data = json.load(f)
    district_index = build_district_index(members_data.get("members", []))
    print(f"Loaded {len(district_index)} GA members for district matching")

    # ── people.csv → LegiScan people_id → OCD person ID ────────────────────
    print("\nProcessing people.csv...")
    people_rows     = read_csv(os.path.join(CSV_DIR, "people.csv"))
    legiscan_to_ocd = {}
    unmatched       = []

    for row in people_rows:
        pid          = get_col(row, "people_id").strip()
        district_str = get_col(row, "district").strip()
        name         = get_col(row, "name").strip()
        key          = parse_district_key(district_str)
        if key:
            ocd_id = district_index.get(key)
            if ocd_id:
                legiscan_to_ocd[pid] = ocd_id
            else:
                unmatched.append(f"{name} ({district_str})")
        else:
            unmatched.append(f"{name} (no district)")

    print(f"  Matched {len(legiscan_to_ocd)}/{len(people_rows)} people by district")
    if unmatched:
        preview = unmatched[:10]
        print(f"  Unmatched ({len(unmatched)}): {', '.join(preview)}"
              + ("..." if len(unmatched) > 10 else ""))

    # ── bills.csv → bill_id → display metadata ──────────────────────────────
    print("\nProcessing bills.csv...")
    bills_rows  = read_csv(os.path.join(CSV_DIR, "bills.csv"))
    bills       = {}
    session_ids = set()

    for row in bills_rows:
        bid    = get_col(row, "bill_id").strip()
        sid    = get_col(row, "session_id").strip()
        if sid:
            session_ids.add(sid)
        bills[bid] = {
            "billNumber": get_col(row, "bill_number", "bill_numb", "bill_num").strip(),
            "title":      get_col(row, "title").strip(),
            "stateLink":  get_col(row, "state_link", "url").strip(),
            "textUrl":    "",  # filled in from documents.csv if present
        }

    print(f"  {len(bills)} bills (session IDs: {', '.join(sorted(session_ids))})")

    # ── documents.csv → latest bill text URL per bill (optional) ────────────
    docs_path = os.path.join(CSV_DIR, "documents.csv")
    if os.path.exists(docs_path):
        print("\nProcessing documents.csv...")
        docs_rows = read_csv(docs_path)
        # Track highest document_id seen per bill — highest ID = most recent version
        best_doc = {}  # bill_id → (document_id_int, url)
        for row in docs_rows:
            bid    = get_col(row, "bill_id").strip()
            doc_id = coerce_int(get_col(row, "document_id", "document_i", "doc_id"))
            url    = get_col(row, "url").strip()
            if not bid or not url:
                continue
            if bid not in best_doc or doc_id > best_doc[bid][0]:
                best_doc[bid] = (doc_id, url)
        # Merge into bills dict
        for bid, (_, url) in best_doc.items():
            if bid in bills:
                bills[bid]["textUrl"] = url
        print(f"  {len(best_doc)} bills with text URLs")
    else:
        print("\nNo documents.csv found — skipping bill text URLs")

    # ── rollcalls.csv → roll_call_id → vote event metadata ──────────────────
    print("\nProcessing rollcalls.csv...")
    rc_rows    = read_csv(os.path.join(CSV_DIR, "rollcalls.csv"))
    votes_meta = {}

    for row in rc_rows:
        rc_id = get_col(row, "roll_call_id", "roll_call_i").strip()
        bid   = get_col(row, "bill_id").strip()
        bill  = bills.get(bid, {})

        votes_meta[rc_id] = {
            "bill":       bill.get("billNumber", ""),
            "billUrl":    bill.get("stateLink", ""),
            "title":      bill.get("title", ""),
            "textUrl":    bill.get("textUrl", ""),
            "motionText": get_col(row, "description", "descriptio").strip(),
            "date":       normalize_date(get_col(row, "date")),
            "yea":        coerce_int(get_col(row, "yea")),
            "nay":        coerce_int(get_col(row, "nay")),
            "chamber":    get_col(row, "chamber").strip(),
        }

    print(f"  {len(votes_meta)} roll calls")

    # ── votes.csv → member_votes by OCD person ID ───────────────────────────
    print("\nProcessing votes.csv...")
    vote_rows    = read_csv(os.path.join(CSV_DIR, "votes.csv"))
    member_votes = {}
    skipped      = 0

    for row in vote_rows:
        rc_id     = get_col(row, "roll_call_id", "roll_call_i").strip()
        pid       = get_col(row, "people_id").strip()
        vote_desc = get_col(row, "vote_desc").strip()

        ocd_id = legiscan_to_ocd.get(pid)
        if not ocd_id or rc_id not in votes_meta:
            skipped += 1
            continue

        vote_label = VOTE_LABEL_MAP.get(vote_desc.lower(), vote_desc or "Other")
        member_votes.setdefault(ocd_id, []).append({
            "voteId": rc_id,
            "vote":   vote_label,
        })

    print(f"  {len(vote_rows):,} records → {len(member_votes)} members with votes ({skipped:,} skipped)")

    # ── Write output ─────────────────────────────────────────────────────────
    session_id = sorted(session_ids)[-1] if session_ids else ""
    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "session":     session_id,
            "sessionName": "Georgia General Assembly",
            "source":      "LegiScan CSV",
            "totalVotes":  len(votes_meta),
        },
        "votes":       votes_meta,
        "memberVotes": member_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(votes_meta)} roll calls · {len(member_votes)} members · {size_kb} KB → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
