#!/usr/bin/env python3
"""Split GA bill sponsorship out of ga-bills.json into an index + per-member slices.

The Sponsored Legislation panel on /ga-legislators/<slug>/ renders ONE member's
bills, but it used to fetch the whole assets/data/ga-bills.json (~6.9MB, 5,656
bills) client-side and scan every bill's sponsors[] to find the handful that are
this member's. Measured against what the panel actually paints, that is ~600x
more bytes than the median member needs — and ga-bills.json is already named in
CLAUDE.md's "Scaling & GitHub limits" section as one of the two blobs that would
hit the 100GB/month bandwidth ceiling first, now fetched by ga-bills.html *and*
all ~247 legislator profiles.

This mirrors build_member_votes_slices.py (same shape: one shared index + tiny
per-member files, written through lib.atomic_io):

  assets/data/ga-sponsorship-index.json   session names (with the URL segment
                                          their bill-text documents live under),
                                          biennium and the bill file's own
                                          generatedAt, plus a
                                          {legisGaGovId: [nPrimary, nCo]} count
                                          map. The counts are what let the page
                                          hide the tab for a member with no
                                          sponsorships — the one thing the old
                                          deferred-6.9MB-fetch design could not
                                          know without paying for the fetch.
  assets/data/ga-sponsorship/<id>.json    one member's rows, ~12KB median.

Slices are keyed on legisGaGovId, NOT the OCD person id: sponsors[] carries only
legisGaGovId, and CLAUDE.md makes it the stable identity (the OCD id is a
cross-reference that a member may not even have).

**Why a slice carries its own bill titles instead of referencing the index.** A
title-bearing index of all 5,656 bills measures ~1.2MB — every visitor would pay
that to read a 12KB panel, a ~60x saving where carrying the rows in the slice is
a ~600x one, and bandwidth-per-view is the ceiling this exists to move. The cost
is duplication on disk (3.8MB of slices for 33k sponsorship records, since a
bill with 290 co-sponsors repeats its title 290 times), which git deltas against
the previous week's near-identical slices; the ~1.2MB index would have had to be
fetched per visit, uncompressed-equivalent, forever. So the index holds only what
is genuinely shared and cheap, and the per-slice `statuses` table interns the
repeated status strings inside the slice instead.

ga-bills.json is left untouched — ga-bills.html legitimately needs all of it.
Run after any step that rewrites ga-bills.json (generation OR the party-tally
enrichment), before `jekyll build`:
    python3 scripts/build_sponsorship_slices.py
"""
from __future__ import annotations

import json
import os

from lib.atomic_io import write_json_atomic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "assets", "data")
BILLS_FILE = os.path.join(DATA_DIR, "ga-bills.json")
MEMBERS_FILE = os.path.join(DATA_DIR, "ga-members.json")
INDEX_OUT = os.path.join(DATA_DIR, "ga-sponsorship-index.json")
SLICES_DIR = os.path.join(DATA_DIR, "ga-sponsorship")

# Chambers that make someone a member of the General Assembly. ga-members.json also
# holds four statewide executives under chamber "executive" (see CLAUDE.md); they
# sponsor nothing, but filtering keeps the index's count map a legislator roster.
VOTING_CHAMBERS = ("Senate", "House of Representatives")


# Every bill's textUrl is this prefix + "<session segment>/<document id>" (verified
# across all 5,656 bills), and the session segment is a property of the session, not
# the bill — so the segment is interned once per session in the index and a row
# stores only the six-digit document id.
TEXT_URL_PREFIX = "https://www.legis.ga.gov/api/legislation/document/"


def split_text_url(url):
    """-> (session segment, document id), or (None, None) if the URL isn't the
    expected shape. A bill whose text link we can't parse simply renders without
    one; guessing a document id would link to the wrong bill's text."""
    if not url or not url.startswith(TEXT_URL_PREFIX):
        return None, None
    parts = url[len(TEXT_URL_PREFIX):].split("/")
    if len(parts) != 2 or not all(parts):
        return None, None
    return parts[0], parts[1]


def compact_row(bill, status_table, status_index):
    """One rendered row, positional to keep slices small:
        [identifier, title, statusIdx, statusDate, legislationId, documentId]

    statusIdx points into the slice's own `statuses` table — the status strings are
    long ("House Committee Favorably Reported By Substitute") and recur across a
    member's bills, so interning them per slice is free compression. legislationId
    stands in for billUrl: every one of the 5,656 bills' billUrl is exactly
    https://www.legis.ga.gov/legislation/<legislationId>, so storing the number and
    rebuilding the URL client-side beats repeating the prefix 33k times. documentId
    does the same for textUrl (the bill text PDF), against the per-session segment
    the index carries.
    """
    status = bill.get("status")
    if status and status not in status_index:
        status_index[status] = len(status_table)
        status_table.append(status)
    return [
        bill.get("identifier"),
        bill.get("title"),
        status_index.get(status, -1) if status else -1,
        # Full timestamp, not just the date: the panel only prints the day, but it
        # sorts on this field, and a chamber acts on dozens of resolutions within one
        # day. Truncating to YYYY-MM-DD threw those into a tie broken by identifier
        # and silently reordered 309 of one member's 382 rows.
        bill.get("statusDate") or None,
        bill.get("legislationId"),
        split_text_url(bill.get("textUrl"))[1],
    ]


def main() -> int:
    if not os.path.exists(BILLS_FILE):
        print(f"build_sponsorship_slices: {BILLS_FILE} not found — skipping.")
        return 0
    with open(BILLS_FILE, encoding="utf-8") as fh:
        data = json.load(fh)

    bills = data.get("bills")
    meta = data.get("metadata") or {}
    if not isinstance(bills, list) or not bills:
        print("build_sponsorship_slices: ga-bills.json carries no bills[] "
              "— refusing to split (an empty slice set would read as "
              "'nobody sponsored anything').")
        return 1

    # Known legislators, so a sponsor id the roster does not recognise is reported
    # rather than quietly written to a slice no page will ever request.
    roster = set()
    if os.path.exists(MEMBERS_FILE):
        with open(MEMBERS_FILE, encoding="utf-8") as fh:
            for m in (json.load(fh).get("members") or []):
                if m.get("chamber") in VOTING_CHAMBERS and m.get("legisGaGovId"):
                    roster.add(int(m["legisGaGovId"]))

    # legisGaGovId -> session id -> {"p": [...], "c": [...]}. Primary vs co-sponsor
    # is split here, not on the client, because it is the split the panel renders and
    # the two say very different things about a legislator.
    by_member: dict[int, dict] = {}
    unknown_sponsors: set[int] = set()
    sponsorships = 0
    # session id -> the segment its text-document URLs use ("2025_26" -> "20252026",
    # "2026_ss" -> "2026EX"). Read off the bills rather than mapped by hand, so a
    # future session needs no code change; first one wins, and a session whose bills
    # carry no parseable text URL simply gets no segment and renders no text links.
    doc_segments: dict[str, str] = {}
    for bill in bills:
        session = bill.get("session") or meta.get("activeSession") or "unknown"
        seg = split_text_url(bill.get("textUrl"))[0]
        if seg and session not in doc_segments:
            doc_segments[session] = seg
        for sp in (bill.get("sponsors") or []):
            gid = sp.get("legisGaGovId")
            if gid is None:
                continue
            gid = int(gid)
            if roster and gid not in roster:
                unknown_sponsors.add(gid)
            sponsorships += 1
            buckets = by_member.setdefault(gid, {}).setdefault(session, {"p": [], "c": []})
            buckets["p" if sp.get("primary") else "c"].append(bill)

    # Clear stale slices first, so a member who drops out of the bill file (a
    # biennium rollover, a re-keyed id) does not keep a dangling file that would
    # render as a live sponsorship record.
    os.makedirs(SLICES_DIR, exist_ok=True)
    for name in os.listdir(SLICES_DIR):
        if name.endswith(".json"):
            os.remove(os.path.join(SLICES_DIR, name))

    counts: dict[str, list] = {}
    sizes = []
    for gid, sessions in by_member.items():
        status_table: list[str] = []
        status_index: dict[str, int] = {}
        out_sessions = {}
        n_primary = n_co = 0
        for sid, buckets in sessions.items():
            rows = {}
            for key in ("p", "c"):
                if not buckets[key]:
                    continue
                rows[key] = [compact_row(b, status_table, status_index) for b in buckets[key]]
                if key == "p":
                    n_primary += len(rows[key])
                else:
                    n_co += len(rows[key])
            if rows:
                out_sessions[sid] = rows
        path = os.path.join(SLICES_DIR, f"{gid}.json")
        write_json_atomic(path, {
            "legisGaGovId": gid,
            "statuses": status_table,
            "sessions": out_sessions,
        }, separators=(",", ":"))
        counts[str(gid)] = [n_primary, n_co]
        sizes.append(os.path.getsize(path))

    # The index is deliberately thin: provenance the panel prints (it must stamp the
    # BILL file's own generatedAt, not the roster stamp at the foot of the page — see
    # CLAUDE.md on per-dataset provenance), the session names and order it groups by,
    # and the counts that decide whether the tab appears at all.
    write_json_atomic(INDEX_OUT, {
        "metadata": {
            "generatedAt": meta.get("generatedAt"),
            "source": meta.get("source"),
            "biennium": meta.get("biennium"),
            "sessions": [{"id": s.get("id"), "name": s.get("name"),
                           "docSegment": doc_segments.get(s.get("id"))}
                         for s in (meta.get("sessions") or []) if s.get("id")],
            "activeSession": meta.get("activeSession"),
            "totalBills": len(bills),
            "totalSponsorships": sponsorships,
            "memberCount": len(counts),
        },
        "members": counts,
    }, separators=(",", ":"))

    sizes.sort()
    median_kb = (sizes[len(sizes) // 2] / 1024) if sizes else 0
    print(f"build_sponsorship_slices: index {os.path.getsize(INDEX_OUT) / 1024:.0f}KB, "
          f"{len(counts)} member slices (median {median_kb:.1f}KB, "
          f"max {sizes[-1] / 1024:.1f}KB) from {sponsorships} sponsorship records "
          f"across {len(bills)} bills.")
    if roster:
        missing = sorted(roster - set(by_member))
        if missing:
            print(f"build_sponsorship_slices: {len(missing)} roster members sponsor "
                  f"nothing in this file (no slice, tab hidden): {missing}")
        if unknown_sponsors:
            print(f"build_sponsorship_slices: WARNING {len(unknown_sponsors)} sponsor "
                  f"legisGaGovId(s) are not in the roster: {sorted(unknown_sponsors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
