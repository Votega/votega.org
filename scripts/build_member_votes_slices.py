#!/usr/bin/env python3
"""Split the monolithic GA roll-call file into a shared index + per-member slices.

The legislator entity pages (/ga-legislators/<id>/) each render ONE member but
used to fetch the whole assets/data/ga-member-votes.json (~3.7MB, 237 members)
client-side, then decode every member's votes and recompute a party-vote index
on every page load — just to show one member's history and party-loyalty stat.

This script derives two lighter artifacts from that same file so a detail page
fetches ~14KB + a shared, cacheable index instead:

  assets/data/ga-votes-index.json      metadata + voteIds + votes, and — the key
                                        move — a precomputed `partyTally` per vote
                                        ({party: {yea, nay}}). That is exactly what
                                        the client's buildPartyVoteIndex() derived
                                        from all members, so with it stored the
                                        client no longer needs anyone else's votes.
  assets/data/ga-votes/<member>.json    one member's compact {index: code} map.

The monolithic ga-member-votes.json is left untouched (ga-majority-tracker.html
still consumes it). Run after generate_ga_votes_data.py, before `jekyll build`:
    python3 scripts/build_member_votes_slices.py

The partyTally computation mirrors buildPartyVoteIndex() in
_includes/entity/ga-legislator.html byte-for-byte in intent: per voter, dedupe by
vote id, count only Yea/Nay, tally by the voter's party. Keep the two in sync.
"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "assets", "data")
VOTES_FILE = os.path.join(DATA_DIR, "ga-member-votes.json")
MEMBERS_FILE = os.path.join(DATA_DIR, "ga-members.json")
INDEX_OUT = os.path.join(DATA_DIR, "ga-votes-index.json")
SLICES_DIR = os.path.join(DATA_DIR, "ga-votes")

# Compact vote codes → the two positions that count toward a party tally. Mirrors
# the CODE map in the client; only Yea/Nay feed party-line math (everything else —
# Not Voting / Present / Absent / Excused / Other — is ignored for the tally).
YEA, NAY = "Y", "N"


def member_slug(member_id: str) -> str:
    """Filesystem-safe slice name for an OCD id (which contains '/'). Must match the
    same transform in the client: id.replace(/[^a-zA-Z0-9]+/g,'-') trimmed of '-'."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", member_id).strip("-")


def build_party_tallies(member_votes, vote_ids, party_by_id):
    """voteId -> {party: {"yea": n, "nay": n}}, counting each voter once per vote.

    member_votes values are compact {indexString: code}; indices point into
    vote_ids. Voters with no known party are skipped (as in the client)."""
    tallies: dict[str, dict] = {}
    for voter_id, compact in member_votes.items():
        party = party_by_id.get(voter_id)
        if not party:
            continue
        seen = set()
        for idx, code in compact.items():
            if code != YEA and code != NAY:
                continue
            vote_id = vote_ids[int(idx)]
            if vote_id in seen:
                continue
            seen.add(vote_id)
            pt = tallies.setdefault(vote_id, {}).setdefault(party, {"yea": 0, "nay": 0})
            pt["yea" if code == YEA else "nay"] += 1
    return tallies


def main() -> int:
    if not os.path.exists(VOTES_FILE):
        print(f"build_member_votes_slices: {VOTES_FILE} not found — skipping.")
        return 0
    with open(VOTES_FILE, encoding="utf-8") as fh:
        data = json.load(fh)

    vote_ids = data.get("voteIds")
    member_votes = data.get("memberVotes") or {}
    votes = data.get("votes") or {}
    if not isinstance(vote_ids, list) or not member_votes:
        print("build_member_votes_slices: file lacks voteIds/memberVotes "
              "(legacy schema) — refusing to split.")
        return 0

    party_by_id = {}
    if os.path.exists(MEMBERS_FILE):
        with open(MEMBERS_FILE, encoding="utf-8") as fh:
            for m in (json.load(fh).get("members") or []):
                if m.get("id") and m.get("party"):
                    party_by_id[m["id"]] = m["party"]

    tallies = build_party_tallies(member_votes, vote_ids, party_by_id)

    # Shared index: the vote metadata every member references, plus the party
    # tallies that used to require the full memberVotes map on the client.
    votes_with_tally = {}
    for vid, meta in votes.items():
        rec = dict(meta)
        if vid in tallies:
            rec["partyTally"] = tallies[vid]
        votes_with_tally[vid] = rec

    index = {
        "metadata": data.get("metadata", {}),
        "voteIds": vote_ids,
        "votes": votes_with_tally,
    }
    with open(INDEX_OUT, "w", encoding="utf-8") as fh:
        json.dump(index, fh, separators=(",", ":"), ensure_ascii=False)

    # Per-member slices — just the member's compact map. Clear stale slices first
    # so a member who leaves the dataset does not keep a dangling file.
    os.makedirs(SLICES_DIR, exist_ok=True)
    for name in os.listdir(SLICES_DIR):
        if name.endswith(".json"):
            os.remove(os.path.join(SLICES_DIR, name))
    for member_id, compact in member_votes.items():
        slug = member_slug(member_id)
        if not slug:
            continue
        with open(os.path.join(SLICES_DIR, slug + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"id": member_id, "compact": compact},
                      fh, separators=(",", ":"), ensure_ascii=False)

    idx_kb = os.path.getsize(INDEX_OUT) / 1024
    print(f"build_member_votes_slices: index {idx_kb:.0f}KB, "
          f"{len(member_votes)} member slices, "
          f"{len(tallies)} votes with party tallies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
