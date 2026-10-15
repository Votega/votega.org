#!/usr/bin/env python3
"""Split federal-member-votes.json into a shared vote index + per-member slices.

Every /us-congress/<slug>/ page renders ONE member, but the entity include used to
fetch the whole federal-member-votes.json — twice, in fact: once for Key Votes and
once for Voting History. That was tolerable while the file held 216 roll calls
attached to enacted laws. Now that generate_federal_votes_data.py enumerates the
chambers' own indexes, the file holds every roll call of the Congress (~1,591), and
shipping the monolith would mean ~1.2 MB on every page load to read one member's
panel.

Same two artifacts the GA legislator page and the federal sponsorship panel already
use (build_member_votes_slices.py, build_sponsorship_slices.py):

  assets/data/federal-votes-index.json    metadata + voteIds + an intern table of
                                          motion text + one positional row per vote
  assets/data/federal-votes/<bioguide>.json
                                          one member's compact {index: code} map

The monolithic federal-member-votes.json is left untouched and stays on the LEGACY
vote schema: publish_federal_delegation.py passes it straight through to
Votega/ga-federal-legislators, so its shape is a published contract, and the party
unity generator that will read it is server-side. The compaction that matters is the
one on the wire, and that is what these artifacts are. (CLAUDE.md's note that
federal-member-votes.json does not use lib/votes_schema.py therefore still holds —
the *slices* use the codec, the monolith does not.)

Run after generate_federal_votes_data.py, before `jekyll build`:
    python scripts/build_federal_votes_slices.py

⚠ The row format below is mirrored by R_* constants in
_includes/entity/federal-legislator.html, which rebuilds each bill's label and
congress.gov permalink from billType + billNumber rather than storing them on every
row. scripts/test_federal_votes_slices.py fails if the two drift.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.atomic_io import write_json_atomic
from lib.votes_schema import encode_member_votes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "assets", "data")
VOTES_FILE = os.path.join(DATA_DIR, "federal-member-votes.json")
INDEX_OUT = os.path.join(DATA_DIR, "federal-votes-index.json")
SLICES_DIR = os.path.join(DATA_DIR, "federal-votes")

#: Positions in an index row. Rows are positional arrays, not objects, because the
#: fourteen field names would otherwise repeat on all ~1,591 records — roughly
#: 140 KB of key names alone. Keep in step with the R_* constants in
#: _includes/entity/federal-legislator.html.
ROW_FIELDS = ("chamber", "date", "billType", "billNumber", "title",
              "motion", "result", "yea", "nay", "tally")
(R_CHAMBER, R_DATE, R_BILLTYPE, R_BILLNUM, R_TITLE,
 R_MOTION, R_RESULT, R_YEA, R_NAY, R_TALLY) = range(len(ROW_FIELDS))

#: The index carries Democratic and Republican totals only, as six flat ints
#: [dYea, dNay, dOther, rYea, rNay, rOther]. That is exactly what the page's
#: buildTallyBar() draws. The full per-party tally (Independents included) stays in
#: the monolith, which is what a server-side party-unity generator will read.
TALLY_PARTIES = ("Democratic", "Republican")


def compact_tally(party_tally):
    """{party: {yea,nay,other}} -> [dY, dN, dO, rY, rN, rO], or None when empty."""
    if not party_tally:
        return None
    row = []
    for party in TALLY_PARTIES:
        bucket = party_tally.get(party) or {}
        row.extend([int(bucket.get("yea") or 0),
                    int(bucket.get("nay") or 0),
                    int(bucket.get("other") or 0)])
    return row if any(row) else None


def compact_result(result):
    """"Pass"/"Fail" -> "P"/"F"; anything else is carried through verbatim.

    Not every roll call answers a pass/fail question: the election of a Speaker
    records the winner's NAME as its result, which `pass_fail()` in the generator
    deliberately passes through rather than asserting a defeat. Collapsing that to
    "F" here would reinstate exactly the error the generator avoids — one row of
    1,591, but a wrong one about a real vote.
    """
    if result == "Pass":
        return "P"
    if result == "Fail":
        return "F"
    return result or ""


def compact_row(meta, motion_index):
    """One vote's positional row. `motion_index` interns the motion text in place."""
    motion = (meta.get("motionText") or "").strip()
    if motion not in motion_index:
        motion_index[motion] = len(motion_index)
    return [
        "H" if meta.get("chamber") == "House" else "S",
        meta.get("date") or "",
        meta.get("billType"),      # null on a quorum call / nomination
        meta.get("billNumber"),
        meta.get("title"),
        motion_index[motion],
        compact_result(meta.get("result")),
        int(meta.get("yea") or 0),
        int(meta.get("nay") or 0),
        compact_tally(meta.get("partyTally")),
    ]


def main() -> int:
    if not os.path.exists(VOTES_FILE):
        print(f"build_federal_votes_slices: {VOTES_FILE} not found — skipping.")
        return 0
    with open(VOTES_FILE, encoding="utf-8") as fh:
        data = json.load(fh)

    votes = data.get("votes") or {}
    member_votes = data.get("memberVotes") or {}
    if not votes or not member_votes:
        print("build_federal_votes_slices: no votes/memberVotes — refusing to split.",
              file=sys.stderr)
        return 1

    # Index order tracks the monolith's (deterministic, enumeration-ordered) votes
    # dict, so a quiet incremental run leaves every member's slice byte-identical.
    compact, vote_ids = encode_member_votes(member_votes, list(votes.keys()))

    motion_index: dict[str, int] = {}
    rows = []
    for vote_id in vote_ids:
        meta = votes.get(vote_id)
        # A member can only reference a vote the monolith carries, so a hole here
        # would mean a malformed file; an empty row keeps positions aligned.
        rows.append(compact_row(meta, motion_index) if meta else None)

    motions = [""] * len(motion_index)
    for text, i in motion_index.items():
        motions[i] = text

    index = {
        "metadata": dict(data.get("metadata") or {}, sliceFormat=list(ROW_FIELDS)),
        "voteIds": vote_ids,
        "motions": motions,
        "rows": rows,
    }
    write_json_atomic(INDEX_OUT, index, separators=(",", ":"))

    # Per-member slices. Clear stale ones first so a member who leaves the dataset
    # does not keep a dangling file the page would still find.
    os.makedirs(SLICES_DIR, exist_ok=True)
    for name in os.listdir(SLICES_DIR):
        if name.endswith(".json"):
            os.remove(os.path.join(SLICES_DIR, name))
    sizes = []
    for bioguide, row in compact.items():
        if not bioguide:
            continue
        path = os.path.join(SLICES_DIR, bioguide + ".json")
        write_json_atomic(path, {"bioguideId": bioguide, "compact": row},
                          separators=(",", ":"))
        sizes.append(os.path.getsize(path))

    idx_kb = os.path.getsize(INDEX_OUT) / 1024
    summary = (f"build_federal_votes_slices: index {idx_kb:.0f}KB "
               f"({len(vote_ids)} votes, {len(motions)} distinct motions), "
               f"{len(sizes)} member slices")
    if sizes:
        summary += (f" (median {sorted(sizes)[len(sizes) // 2] / 1024:.1f}KB, "
                    f"max {max(sizes) / 1024:.1f}KB)")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
